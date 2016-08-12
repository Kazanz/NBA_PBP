import sys
import re
from copy import deepcopy
from urllib2 import urlopen

from bs4 import BeautifulSoup
from tqdm import tqdm

from db import player_box_score_table, team_box_score_table
from pbp_methods import METHODS
from performance_measure import PerformanceMeasureCaclulator


def make_soup(url):
    return BeautifulSoup(urlopen(url), "lxml")


def get_team(row):
    return re.findall('\w+\.png', row.img.attrs['src'])[0][:-4]


def get_home_away(soup):
    home_src = soup.find('div', 'home').find('img').attrs['src']
    away_src = soup.find('div', 'away').find('img').attrs['src']
    home = re.findall('\w+?\.png', home_src)[0][:-4]
    away = re.findall('\w+?\.png', away_src)[0][:-4]
    return home, away


def get_play_by_play(gameid):
    "Returns the play-by-play data for a given game id."

    print("Getting play-by-play for game: {}".format(gameid))

    url = "http://espn.go.com/nba/playbyplay?gameId={}".format(gameid)
    soup = make_soup(url)
    home, away = get_home_away(soup)
    tables = soup.find('article', 'play-by-play').findAll('table')
    data = []
    for i, table in enumerate(tables):
        quarter = i + 1
        rows = [row.find_all("td") for row in table.find_all("tr")]
        for row in rows:
            if not row:
                continue
            team = get_team(row[1])
            away_score, home_score = row[3].string.split(' - ')
            data.append({
                "time": row[0].string,
                "quarter": quarter,
                "play": row[2].string.replace(u"\xa0", u""),
                "team": team,
                'home': team == home,
                'away': team == away,
                "home_score": int(home_score),
                "away_score": int(away_score),
            })
    if data[-1]['away_score'] > data[-1]['home_score']:
        winner = away
    else:
        winner = home
    return data, home, away, winner


def get_roster(gameid, home, away):
    def extract_names(div):
        names = []
        for row in div.findAll("tr")[1:]:
            tds = row.findAll("td")
            if not tds:
                continue
            try:
                link = tds[0].find("a")["href"]
            except (TypeError, AttributeError):
                continue
            soup = make_soup(link)
            names.append(soup.div("div", "mod-content")[0].find("h1").text)
        return names

    roster = {}
    url = "http://www.espn.com/nba/boxscore?gameId={}".format(gameid)
    soup = make_soup(url)
    away_div = soup.find("div", "gamepackage-away-wrap")
    home_div = soup.find("div", "gamepackage-home-wrap")
    roster[away] = extract_names(away_div)
    roster[home] = extract_names(home_div)
    return roster


class PlayByPlayToBoxScoreWriter(object):
    """Create a running boxscore from play by play data and write it to a db."""

    def __init__(self, individual_table, team_table, gameid, debug=False):
        # General
        self.debug = debug
        self.rows = []
        self.aggregate_rows = []
        self.individual_table = individual_table
        self.team_table = team_table
        self.gameid = gameid
        self.pbp, self.home, self.away, self.winner = get_play_by_play(gameid)

        # Sub and Time Tracking
        self.seconds_played_by_player = {}
        self.players_in_game = self.set_starters(gameid)
        self.quarter_starters = {1: deepcopy(self.players_in_game)}
        self.players_ending_last_quarter = {}
        self.made_a_play_this_quarter = []
        self.current_quarter = 1
        self.current_time = "12:00"

        # Scores
        self.roster = get_roster(self.gameid, self.home, self.away)
        self.running_box_score = self._default_running_box_score(self.roster)

    def _default_running_box_score(self, roster):
        for team in roster.keys():
            roster[team] = {name: {
                'in_game': name in self.players_in_game
            } for name in roster[team]}
        return roster

    def execute(self):
        for play in tqdm(self.pbp, desc="Analyzing Plays"):
            stats = self.handle_play(play)
            if not stats:
                continue
            self.update_player_stats(stats)
            formatted = self.format_box_score(play, self.running_box_score)
            self.stage_player_level_data(play, formatted)
            self.assure_players_in_game(stats)
            #self.print_bad_time(4, "11:33", 6)
            print(self.quick_sum(), self.quick_names())
        self.write_to_db()

    def handle_play(self, play):
        self.update_minutes_played(play['quarter'], play['time'])
        if self.end_of_quarter(play):
            return
        if self.make_sub(play):
            return
        return self.play_to_stats(play)

    def play_to_stats(self, play):
        for method in METHODS:
            stats = method(play['play'])
            if stats:
                return stats
        if self.debug:
            print("No stat for: {}".format(play['play']))

    def update_player_stats(self, play_stats):
        for player, stats in play_stats.items():
            self.made_a_play_this_quarter.append(player)
            self.update_running_box_score(self.get_team(player), player, stats)

    def get_team(self, player):
        for team, players in self.roster.items():
            if player in players:
                return team

    def update_running_box_score(self, team, player, stats):
        if player not in self.running_box_score[team]:
            self.running_box_score[team][player] = stats
        else:
            for stat, amount in stats.items():
                self.running_box_score[team][player].setdefault(stat, 0)
                self.running_box_score[team][player][stat] += amount
        min_stat = self.get_players_minutes(player)
        self.running_box_score[team][player]['MIN'] = min_stat

    def format_box_score(self, play, box_score):
        stats = {}
        box_score = deepcopy(box_score)
        if play['quarter'] == 4:
            import pdb; pdb.set_trace();
        for team, players_stats in box_score.items():
            stats.setdefault(team, [])
            for player, player_stats in players_stats.items():
                player_stats['player'] = player
                player_stats['team'] = team
                player_stats['time'] = play['time']
                player_stats['quarter'] = play['quarter']
                in_game = player in self.players_in_game
                player_stats['in_game'] = in_game
                stats[team].append(player_stats)
        return stats

    ############ THIS MUST BE CALCULATED AFTER THE FACT ################## CUZ OF SUBS
    def stage_player_level_data(self, play, box_score):
        """Stage the box score for writing to the database."""
        if self._duplicate_time(box_score.values()[0], self.rows):
            self._remove_last_staged_row()
        for stats in box_score.values():
            for player_stat in stats:
                player_stat['play'] = play['play']
                player_stat['home'] = player_stat['team'] == self.home
                player_stat['home_score'] = play['home_score']
                player_stat['away_score'] = play['away_score']
                player_stat['winner'] = self.winner
                self.rows.append(player_stat)

    def _duplicate_time(self, stats, rows):
        """When shooting freethrows (and other instances) multiple recorded
        plays can happend at the same time.  Therefore we just record the
        last play at that time in that quarter.  We use the staged row for
        this purpose."""
        if not rows or not stats:
            return False
        for key in ['quarter', 'time']:
            if stats[0][key] != rows[-1][key]:
                return False
        return True

    def _remove_last_staged_row(self):
        quarter = self.rows[-1]['quarter']
        time = self.rows[-1]['time']
        for i in range(len(self.rows)-1, 0, -1):
            row = self.rows[i]
            if row['quarter'] == quarter and row['time'] == time:
                del self.rows[i]

    def stage_team_level_data(self, box_score):
        """Stage the aggregate team box score for writing to the database."""
        aggregate_stats = {}
        uneeded_fields = ['away_score', 'home_score', 'time', 'home', 'quarter',
                          'winner', 'MIN', 'team', 'player']
        for team, stats in box_score.items():
            aggregate_stats.setdefault(team, {})
            for player_stat in stats:
                winner = player_stat['winner']
                time = player_stat['time']
                for field, value in player_stat.items():
                    if field in uneeded_fields:
                        continue
                    aggregate_stats[team].setdefault(field, 0)
                    try:
                        aggregate_stats[team][field] += value
                    except TypeError:
                        del aggregate_stats[team][field]
            aggregate_stats[team]['winner'] = winner
            aggregate_stats[team]['team'] = team
            aggregate_stats[team]['time'] = time
            aggregate_stats[team]['gameid'] = self.gameid
        self.aggregate_rows += aggregate_stats.values()

    def write_to_db(self):
        # This needs to happen here.
        # box_score = self.add_perf_measures(formatted)
        for row in tqdm(self.rows, desc="Writing Player Data"):
            self.individual_table.insert(row)
        for row in tqdm(self.aggregate_rows, desc="Writing Team Data"):
            self.team_table.insert(row)

    def add_perf_measures(self, stats):
        calc = PerformanceMeasureCaclulator(stats)
        calc.update_stats()
        return calc.stats

    #####################
    # MIN TRACKING CODE #
    #####################

    @property
    def players_minutes(self):
        return {k: (v // 60) for k, v in self.seconds_played_by_player.items()}

    def get_players_minutes(self, player):
        if player not in self.seconds_played_by_player:
            seconds_elapsed = self._seconds_elapsed(
                self.current_quarter, self.current_time, last_time="12:00")
            self.seconds_played_by_player[player] = seconds_elapsed
        return self.players_minutes[player]

    def set_starters(self, gameid):
        url = "http://www.espn.com/nba/boxscore?gameId={}".format(gameid)
        soup = make_soup(url)
        data = soup.findAll('div', 'hide-bench')
        players_in_game = []
        for players in data:
            for link in [a.attrs['href'] for a in players.findAll('a')[:5]]:
                soup = make_soup(link)
                player = soup.find('div', 'mod-content').find('h1').text
                players_in_game.append(player)
        return players_in_game

    def update_minutes_played(self, quarter, time):
        seconds_elapsed = self._seconds_elapsed(quarter, time)
        for player in self.players_in_game:
            self.seconds_played_by_player.setdefault(player, 0)
            self.seconds_played_by_player[player] += seconds_elapsed

    def _seconds_elapsed(self, quarter, time, last_time=None):
        if last_time:
            last_min, last_sec = map(int, last_time.split(':'))
        else:
            last_min, last_sec = map(int, self.current_time.split(':'))
        if last_sec == 0:
            last_min -= 1
            last_sec = 60
        self.current_time = time
        now_min, now_sec = map(int, time.split(':'))
        quarter_diff = quarter - self.current_quarter
        self.current_quarter = quarter
        total_seconds = 0
        if quarter_diff == 1:
            total_seconds += last_min * 60
            total_seconds += last_sec
            quarter_length_min = 12 if quarter <= 4 else 5
            total_seconds += (quarter_length_min - now_min - 1) * 60
            total_seconds += 60 - now_sec
        elif quarter_diff == 0:
            total_seconds += (last_min - now_min) * 60 + (last_sec - now_sec)
        return total_seconds

    #####################
    # SUBSTITUTION CODE #
    #####################

    def end_of_quarter(self, play):
        if re.findall('End of', play['play']):
            self.check_for_inactive_players(play['quarter'])
            players = deepcopy(self.players_in_game)
            self.players_ending_last_quarter[play['quarter']] = players
            self.made_a_play_this_quarter = []
            return True

    def check_for_inactive_players(self, quarter):
        """Sometimes a player will end a quarter and then not come in again
        in the next quarter.  We need to account for this, and change their
        `in_game` value for the last quarter and remove them from the active
        players."""
        if quarter == 1:
            return
        for player in self.players_in_game:
            if player not in self.made_a_play_this_quarter:
                self.players_in_game.remove(player)
                self.make_adjustment(self.create_adjustment(player, 0))  # TODO: CHECK IF THIS EFFECTS MINUTES

    def make_sub(self, play):
        if re.findall('enters the game for', play['play']):
            player1, player2 = play['play'].split(" enters the game for ")
            self.sub_in(play['team'], player1)
            self.sub_out(play['team'], player2)
            return True
        return False

    def sub_in(self, team, player):
        self.seconds_played_by_player.setdefault(player, 0)
        if player not in self.players_in_game:
            self.players_in_game.append(player)
        else:
            self.make_adjustment(self.create_adjustment(player, -1))
        self.running_box_score[team][player]['in_game'] = True

    def sub_out(self, team, player):
        if player in self.players_in_game:
            self.players_in_game.remove(player)
        else:
            self.make_adjustment(self.create_adjustment(player, 1))
        self.running_box_score[team][player]['in_game'] = False

    def assure_players_in_game(self, players):
        for player in players:
            if player not in self.players_in_game:
                self.players_in_game.append(player)
                self.make_adjustment(self.create_adjustment(player, 1))

    def make_adjustment(self, adjustment):
        for row in self.rows:
            if row['player'] == adjustment['player'] and \
                    row['quarter'] == adjustment['quarter']:
                row.setdefault('MIN', 0)
                row['MIN'] += adjustment['MIN']
                row['in_game'] = adjustment['in_game']

    def create_adjustment(self, player, modifier):
        """When a player is subbed in at the start of a quarter,
        play by play does not track it.  Therfore we must deduce when
        this happened by observing when a player is subbed out that we
        did not think was in the game, and cross-reference that with the
        players we thought ended the last quarter to adjust the minuted
        played stat.  This adjustment should be detected on whatever is
        using the make_substitution method and adjusted there.
        (Not the best design pattern, could be refactor)

        :param player: player entering the game.
        :param modifier: 1 or -1 depending on need to add or subtract minutes.
        """
        quarter_length_min = 12 if self.current_quarter <= 4 else 5
        time_adjust = quarter_length_min - int(
            self.current_time.split(':')[0])
        return {
            'player': player,
            'MIN': time_adjust * modifier,
            'quarter': self.current_quarter,
            'in_game': modifier > 0,
        }

    #################
    # FOR DEBUGGING #
    #################

    def quick_sum(self):
        """DELETE THIS LATER"""
        in_game = 0
        for k, v in self.running_box_score.items():
            for k, v in v.items():
                if v.get('in_game'):
                    in_game += 1
        return in_game

    def quick_names(self):
        """DELETE THIS LATER"""
        names = {}
        for team, v in self.running_box_score.items():
            for k, v in v.items():
                if v.get('in_game'):
                    names.setdefault(team, [])
                    names[team].append(k)
        return names

    def print_faulty_time(self):
        """DELETE THIS LATER: Finds time when the wrong amount of players
        are in the game."""
        quarter = None
        time = None
        in_game = 0
        for row in self.rows:
            if row['quarter'] == quarter and row['time'] == time:
                in_game += int(row.get('in_game', 0))
            else:
                if quarter is not None and time is not None and in_game != 10:
                    print("FAULT:", quarter, time, in_game)
                    sys.exit()
                quarter = row['quarter']
                time = row['time']
                in_game = int(row.get('in_game', 0))

    def print_bad_time(self, quarter, time, bad_num):
        players = {}
        count = 0
        for row in self.rows:
            if row['quarter'] == quarter and row['time'] == time:
                if row.get('in_game'):
                    count += 1
                    players.setdefault(row['team'], [])
                    players[row['team']].append(row['player'])
        from pprint import pprint
        pprint(count)
        pprint(players)
        #pprint(self.players_in_game)
        if count != 10 and count != 0 and quarter == 4:
            sys.exit()


if __name__ == '__main__':
    PlayByPlayToBoxScoreWriter(
        player_box_score_table, team_box_score_table,
        '400878160', debug=len(sys.argv) > 1).execute()
