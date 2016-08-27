import sys
import re
from collections import OrderedDict
from copy import deepcopy
from urllib2 import urlopen

from bs4 import BeautifulSoup
from tqdm import tqdm

from db import player_box_score_table, team_box_score_table, game_table
from pbp_methods import METHODS
from performance_measure import PlayByPlayPerformanceMeasureCalculator


class BadGameIDError(Exception):
    pass


def make_soup(url):
    res = urlopen(url)
    if res.url == 'http://www.espn.com/nba/scoreboard':
        raise BadGameIDError("Not a valid gameid")
    return BeautifulSoup(res, "lxml")


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
                "play": row[2].string.replace(u"\xa0", u"").strip(' .!?,'),
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
    """Create a running boxscore from play by play data and write it to a db.

    NOTE: Minutes are now calculated after the fact, so the minute
    recalculating during the initial read is uncesserary, just havn't
    removed it.
    """

    def __init__(self, individual_table, team_table, game_table, gameid,
                 debug=False):
        # General
        self.debug = debug
        self.rows = []
        self.aggregate_rows = []
        self.individual_table = individual_table
        self.team_table = team_table
        self.game_table = game_table
        self.gameid = gameid
        self.pbp, self.home, self.away, self.winner = get_play_by_play(gameid)

        # Sub and Time Tracking
        self.seconds_played_by_player = {}
        self.players_in_game = self.set_starters(gameid)
        self.quarter_starters = {1: deepcopy(self.players_in_game)}
        self.players_ending_last_quarter = {}
        self.in_a_play_this_quarter = []
        self.current_quarter = 1
        self.current_time = "12:00"

        # Scores
        self.roster = get_roster(self.gameid, self.home, self.away)
        self.running_box_score = self._default_running_box_score(self.roster)

        # Set stats for Q1 - 12:00
        play = {
            "play": "Start of game",
            "quarter": 1,
            "time": "12:00",
            "team": None,
            "home_score": 0,
            "away_score": 0,
        }
        formatted = self.format_box_score(play, self.running_box_score)
        self.stage_player_level_data(play, formatted)

    def _default_running_box_score(self, roster):
        for team in roster.keys():
            roster[team] = {name: {
                'in_game': name in self.players_in_game
            } for name in roster[team]}
        return roster

    def execute(self):
        for play in tqdm(self.pbp, desc="Analyzing Plays"):
            stats = self.handle_play(play)
            if stats is None:
                continue
            try:
                self.update_player_stats(stats)
            except KeyError:
                # Not a real player.  Most likely a team rebound.
                print("Can't update stats: {}".format(stats))
                continue
            formatted = self.format_box_score(play, self.running_box_score)
            self.stage_player_level_data(play, formatted)
            self.assure_players_in_game(stats)
        self.fill_in_to_end_of_game()
        self.rows = self.add_minutes_played(self.rows)
        self.rows = self.add_perf_measures(self.rows)
        self.write_game_data(self.gameid)
        self.write_player_data()
        self.write_team_data()

    def handle_play(self, play):
        self.update_minutes_played(play['quarter'], play['time'])
        if self.end_of_game(play):
            return
        elif self.end_of_quarter(play):
            return
        elif self.make_sub(play):
            return {}
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
            self.in_a_play_this_quarter.append(player)
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

    def stage_player_level_data(self, play, box_score):
        """Stage the box score for writing to the database."""
        self.fill_in_missing_times(play['quarter'], play['time'])
        if self._duplicate_time(box_score.values()[0], self.rows):
            # For plays that happend at the same second.
            play['play'] += ', {}'.format(self.rows[-1]['play'])
            self._remove_last_staged_row()
        for stats in box_score.values():
            for player_stat in stats:
                player_stat['play'] = play['play']
                player_stat['home'] = player_stat['team'] == self.home
                player_stat['home_score'] = play['home_score']
                player_stat['away_score'] = play['away_score']
                player_stat['winner'] = self.winner
                self.rows.append(player_stat)

    def fill_in_to_end_of_game(self):
        """Fills in the times between last play and end of game."""
        previous_rows = self._rows_from_last_time()
        last_quarter = previous_rows[-1]['quarter']
        last_time = previous_rows[-1]['time']
        skipped_times = self._times_between_times(
            last_time, "0:00", last_quarter, 4)
        for quarter, time in skipped_times:
            for row in previous_rows:
                row = {k: v for k, v in row.items()}  # Safe duplicate
                row['play'] = None
                row['quarter'] = quarter
                row['time'] = time
                self.rows.append(row)

    def fill_in_missing_times(self, quarter, time):
        """Fills in the times between plays where plays did not happen."""
        if not self.rows:
            return
        previous_rows = self._rows_from_last_time()
        last_row = self.rows[-1]
        skipped_times = self._times_between_times(
            last_row['time'], time, last_row['quarter'], quarter)
        for quarter, time in skipped_times:
            for row in previous_rows:
                row = {k: v for k, v in row.items()}  # Safe duplicate
                row['play'] = None
                row['quarter'] = quarter
                row['time'] = time
                self.rows.append(row)

    def _times_between_times(self, first, second, start_quarter, end_quarter):
        times = []
        if start_quarter != end_quarter:
            times += self._times_between_times(
                first, "0:00", start_quarter, start_quarter)
            times += self._times_between_times(
                "12:00", second, end_quarter, end_quarter)
            return times
        else:
            fmin, fsec = map(int, first.split(":"))
            smin, ssec = map(int, second.split(":"))
            for m in range(fmin, smin-1, -1):
                sec_source = 60 if m != fmin else fsec-1
                sec_target = 0 if m != smin else ssec
                for s in range(sec_source, sec_target, -1):
                    s = str(s) if len(str(s)) == 2 else "0{}".format(s)
                    times.append((start_quarter, "{}:{}".format(m,s)))
        return times

    def _rows_from_last_time(self):
        rows = []
        quarter = self.rows[-1]['quarter']
        time = self.rows[-1]['time']
        for i in range(len(self.rows)-1, 0, -1):
            row = self.rows[i]
            if row['quarter'] == quarter and row['time'] == time:
                rows.append(row)
            else:
                break
        return rows

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
            else:
                break

    def write_game_data(self, gameid):
        soup = make_soup("http://www.espn.com/nba/game?gameId={}".format(gameid))
        date = soup.find('title').text.split('-')
        if date:
            date = date[-2].strip()
        location = soup.find(
            "div", "location-details").find('li').text.strip("\t\n")
        attendance = re.sub("[^0-9]", "", soup.find('div', 'capacity').text)
        capacity = re.sub(
            "[^0-9]", "",
            soup.find('div', 'attendance').find('div', 'capacity').text
        )
        refs = soup.findAll("div", "game-info-note")
        if refs:
            refs = refs[-1].find('span').text
        self.game_table.insert(dict(gameid=gameid, date=date, location=location,
                                   attendance=attendance, capacity=capacity,
                                   refs=refs))

    def write_team_data(self):
        """Stage the aggregate team box score for writing to the database."""
        order = ['gameid', 'quarter', 'time', 'team', 'MIN', 'PTS', 'FGM',
                 'FGA', '3PM', '3PA', 'FTM', 'PTA', 'TREB', 'OREB', 'DREB',
                 'AST', 'STL', 'BLK', 'TO', 'PF', 'PFD', 'winner']
        uneeded_fields = ['away_score', 'home_score', 'time', 'home', 'quarter',
                          'winner', 'MIN', 'team', 'player', 'play', 'gameid',
                          'in_game']
        last_quarter = None
        last_time = None
        aggregates = {self.home: {}, self.away: {}}
        for row in tqdm(self.rows, desc="Writing team data"):
            quarter = row['quarter']
            time = row['time']
            team = row['team']
            if last_quarter is None:
                last_quarter = quarter
                last_time = time
            elif quarter != last_quarter or time != last_time:
                last_quarter = quarter
                last_time = time
                for stats in aggregates.values():
                    self.team_table.insert(self.order_row(stats, order))
                aggregates = {self.home: {}, self.away: {}}
            for field, value in row.items():
                if field in uneeded_fields:
                    continue
                aggregates[team].setdefault(field, 0)
                try:
                    aggregates[team][field] += value
                except TypeError:
                    del aggregates[team][field]
                aggregates[team]['winner'] = row['winner']
                aggregates[team]['team'] = row['team']
                aggregates[team]['time'] = row['time']
                aggregates[team]['quarter'] = row['quarter']
                aggregates[team]['gameid'] = self.gameid


    def write_player_data(self):
        order = ['gameid', 'quarter', 'time', 'team', 'player', 'in_game',
                 'uPER', 'PIR', 'MIN', 'PTS', 'FGM', 'FGA', '3PM', '3PA', 'FTM',
                 'PTA', 'TREB', 'OREB', 'DREB', 'AST', 'STL', 'BLK', 'TO', 'PF',
                 'PFD', 'home', 'home_score', 'away_score', 'winner', 'play']
        for row in tqdm(self.rows, desc="Writing Player Data"):
            row['gameid'] = self.gameid
            self.individual_table.insert(self.order_row(row, order))

    def order_row(self, row, order):
        row['gameid'] = self.gameid
        data = OrderedDict()
        for field in order:
            data[field] = row.get(field, 0)
        return data

    def add_minutes_played(self, rows):
        first_play_time = rows[0]['time']
        players = reduce(lambda x, y: x.keys() + y.keys(), self.roster.values())
        # Not efficient, but easier to think about.
        for player in tqdm(players, desc="Calculating MIN"):
            players_seconds = 0
            last_time = "12:00"
            last_quarter = 1
            in_game = False
            for row in rows:
                if row['player'] != player:
                    continue
                elif not row['in_game']:
                    last_time = row['time']
                    last_quarter = row['quarter']
                    row['MIN'] = self.seconds_to_minutes(players_seconds)
                    in_game = False
                    continue
                elif not in_game and row['time'] != first_play_time:
                    last_time = row['time']
                    last_quarter = row['quarter']
                    row['MIN'] = self.seconds_to_minutes(players_seconds)
                    in_game = True
                    continue
                else:
                    quarter = row['quarter']
                    time = row['time']
                    players_seconds += self.calc_seconds(
                        quarter, time, last_quarter, last_time)
                    row['MIN'] = self.seconds_to_minutes(players_seconds)
                    last_time = row['time']
                    last_quarter = row['quarter']
        return rows

    def calc_seconds(self, quarter, time, last_quarter, last_time):
        if last_quarter != quarter:
            last_time = "12:00" if quarter <= 4 else "5:00"
        last_min, last_sec = map(int, last_time.split(':'))
        if last_sec == 0:
            last_min -= 1
            last_sec = 60
        now_min, now_sec = map(int, time.split(':'))
        return (last_min - now_min) * 60 + (last_sec - now_sec)

    def seconds_to_minutes(self, seconds):
        if seconds == 0:
            return 0
        return (seconds // 60) or 1

    def add_perf_measures(self, stats):
        calc = PlayByPlayPerformanceMeasureCalculator(self.rows)
        return calc.update_rows()

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

    def end_of_game(self, play):
        return re.findall('End of Game', play['play'])

    def end_of_quarter(self, play):
        if re.findall('End of', play['play']):
            self.check_for_inactive_players(play['quarter'])
            players = deepcopy(self.players_in_game)
            self.players_ending_last_quarter[play['quarter']] = players
            self.in_a_play_this_quarter = []
            return True

    def check_for_inactive_players(self, quarter):
        """Sometimes a player will end a quarter and then not come in again
        in the next quarter.  We need to account for this, and change their
        `in_game` value for the last quarter and remove them from the active
        players."""
        if quarter == 1:
            return
        for player in self.players_in_game:
            if player not in self.in_a_play_this_quarter:
                self.players_in_game.remove(player)
                self.make_adjustment(self.create_adjustment(player, 0))


    def make_sub(self, play):
        if re.findall('enters the game for', play['play']):
            player1, player2 = play['play'].split(" enters the game for ")
            self.in_a_play_this_quarter.append(player1)
            self.in_a_play_this_quarter.append(player2)
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
        seconds = adjustment['MIN'] * 60
        self.seconds_played_by_player[adjustment['player']] += seconds

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


def write_errored(gameid, filename, method="a"):
    with open(filename, method) as f:
        f.write(str(gameid) + ",")


def write_many(amount):
    def stop(completed, amount, last_gameid, max_gameid):
        return amount == completed if amount else last_gameid == max_gameid

    with open("error_gameids.txt", "r") as f:
        errors = set(f.readlines()[0].split(','))
        write_errored(",".join(errors), "error_gameids.txt", "w")
    with open("skipped_gameids.txt", "r") as f:
        skip = set(f.readlines()[0].split(','))
        write_errored(",".join(skip), "skipped_gameids.txt", "w")
    skip.update(errors)

    min_gameid, max_gameid = (271102003, 400878160)
    completed = 0
    gameid = min_gameid - 1
    while not stop(completed, amount, gameid, max_gameid):
        gameid += 1
        if gameid in skip:
            continue
        try:
            PlayByPlayToBoxScoreWriter(
                player_box_score_table, team_box_score_table, game_table,
                gameid, debug=len(sys.argv) > 2).execute()
        except BadGameIDError:
            write_errored(gameid, "skipped_gameids.txt")
        except KeyError as e:
            print("A key error occured in game: {}!".format(gameid))
            print(e.message)
            write_errored(gameid, "error_gameids.txt")
        except AttributeError as e:
            print("An attribute error occured in game: {}!".format(gameid))
            print(e.message)
            write_errored(gameid, "error_gameids.txt")
        completed += 1

if __name__ == '__main__':
    """Known Errors:

    1. Players whos name on espn.com profile do not match their
    play-by-play name will throw and error and the game will be ignored.
    (Perhaps we could do a closest match algorithm to the name? like take
    streaks of letters and add them together or something?)

    2. Sometimes the "home team" cannot be found.  Not sure why yet.
    """
    write_many(sys.argv[1] if len(sys.argv) > 1 else None)
