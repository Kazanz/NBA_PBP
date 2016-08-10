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


class SubstitutionTracker(object):
    """Keeps track of minutes played in the play-by-play for each player."""
    seconds_played_by_player = {}
    players_in_game = []
    players_ending_last_quarter = []
    last_quarter = 1
    last_time = "12:00"

    def __init__(self, gameid):
        self._set_starters(gameid)

    @property
    def players_minutes(self):
        return {k: (v // 60) for k, v in self.seconds_played_by_player.items()}

    def get_players_minutes(self, player):
        if player not in self.seconds_played_by_player:
            seconds_elapsed = self._seconds_elapsed(
                self.last_quarter, self.last_time, last_time="12:00")
            self.seconds_played_by_player[player] = seconds_elapsed
        return self.players_minutes[player]

    def check_end_of_quarter(self, play):
        if re.findall('End of', play):
            self.players_ending_last_quarter = deepcopy(self.players_in_game)
            return True

    def make_substitution(self, play, time):
        self.adjustment = None
        if re.findall('enters the game for', play):
            player1, player2 = play.split(" enters the game for ")
            if player1 not in self.players_in_game:
                self.players_in_game.append(player1)
            if player2 in self.players_in_game:
                self.players_in_game.remove(player2)
            else:
                self.adjustment = self.create_adjustment(player1)
            self.seconds_played_by_player.setdefault(player1, 0)
            return True,

    def create_adjustment(self, player):
        """When a player is subbed in at the start of a quarter,
        play by play does not track it.  Therfore we must deduce when
        this happened by observing when a player is subbed out that we
        did not think was in the game, and cross-reference that with the
        players we thought ended the last quarter to adjust the minuted
        played stat.  This adjustment should be detected on whatever is
        using this method and adjusted there. (Not the best design pattern,
        could be refactor)

        :param player: player entering the game.
        """
        quarter_length_min = 12 if self.last_quarter <= 4 else 5
        if player in self.players_ending_last_quarter:
            time_adjust = quarter_length_min - int(self.last_time.split(':')[0])
            return {
                'player': player,
                'MIN': time_adjust,
                'quarter': self.last_quarter,
            }

    def update_minutes_played(self, quarter, time):
        seconds_elapsed = self._seconds_elapsed(quarter, time)
        for player in self.players_in_game:
            self.seconds_played_by_player.setdefault(player, 0)
            self.seconds_played_by_player[player] += seconds_elapsed

    def _seconds_elapsed(self, quarter, time, last_time=None):
        if last_time:
            last_min, last_sec = map(int, last_time.split(':'))
        else:
            last_min, last_sec = map(int, self.last_time.split(':'))
        if last_sec == 0:
            last_min -= 1
            last_sec = 60
        self.last_time = time
        now_min, now_sec = map(int, time.split(':'))
        quarter_diff = quarter - self.last_quarter
        self.last_quarter = quarter
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

    def _set_starters(self, gameid):
        url = "http://www.espn.com/nba/boxscore?gameId={}".format(gameid)
        soup = make_soup(url)
        data = soup.findAll('div', 'hide-bench')
        for players in data:
            for link in [a.attrs['href'] for a in players.findAll('a')[:5]]:
                soup = make_soup(link)
                player = soup.find('div', 'mod-content').find('h1').text
                self.players_in_game.append(player)


class PlayByPlayToBoxScoreWriter(object):
    """Create a running boxscore from play by play data and write it to a db."""

    def __init__(self, individual_table, team_table, gameid, debug=False):
        self.debug = debug
        self.rows = []
        self.aggregate_rows = []
        self.individual_table = individual_table
        self.team_table = team_table
        self.gameid = gameid
        self.pbp, self.home, self.away, self.winner = get_play_by_play(gameid)
        self.running_box_score = {}
        self.subtracker = SubstitutionTracker(gameid)

    def execute(self):
        for play in tqdm(self.pbp, desc="Analyzing Plays"):
            self.subtracker.update_minutes_played(play['quarter'], play['time'])
            play_stats = self.play_to_stats(play)
            if play_stats:
                team = play['team']
                self.running_box_score.setdefault(team, {})
                self.update_player_stats(team, play, play_stats)
                box_score = self.add_PER(play, self.running_box_score)
                self.stage_player_level_data(play, box_score)
                self.stage_team_level_data(play, box_score)
        self.write_to_db()

    def play_to_stats(self, play):
        if not self.subtracker.check_end_of_quarter(play['play']) \
                and not self.is_sub(play):
            for method in METHODS:
                stats = method(play['play'])
                if stats:
                    return stats
            if self.debug:
                print("No stat for: {}".format(play['play']))

    def is_sub(self, play):
        if self.subtracker.make_substitution(play['play'], play['time']):
            # Adjust for unrecorded quarter substitutions.
            adjustment = self.subtracker.adjustment
            if adjustment:
                for row in self.rows:
                    if row['player'] == adjustment['player'] and \
                            row['quarter'] == adjustment['quarter']:
                        row['MIN'] -= adjustment['MIN']
            return True

    def update_player_stats(self, team, play, play_stats):
        for player, stats in play_stats.items():
            stats['MIN'] = self.get_time(play, player)
            if player not in self.running_box_score[team]:
                self.running_box_score[team][player] = stats
            else:
                self.update_running_box_score(team, player, stats)

    def get_time(self, play, player):
        return self.subtracker.get_players_minutes(player)

    def update_running_box_score(self, team, player, stats):
        for stat, amount in stats.items():
            self.running_box_score[team][player].setdefault(stat, amount)
            if stat == "MIN":
                self.running_box_score[team][player][stat] = amount
            else:
                self.running_box_score[team][player][stat] += amount

    def add_PER(self, play, box_score):
        stats = self.format_box_score_for_per_calc(play, deepcopy(box_score))
        calc = PerformanceMeasureCaclulator(stats)
        calc.update_stats()
        return calc.stats

    def format_box_score_for_per_calc(self, play, box_score):
        stats = {}
        for team, players_stats in box_score.items():
            stats.setdefault(team, [])
            for player, player_stats in players_stats.items():
                player_stats['player'] = player
                player_stats['team'] = team
                player_stats['time'] = play['time']
                player_stats['quarter'] = play['quarter']
                stats[team].append(player_stats)
        return stats

    def stage_player_level_data(self, play, box_score):
        """Stage the box score for writing to the database."""
        for stats in box_score.values():
            for player_stat in stats:
                player_stat['home'] = player_stat['team'] == self.home
                player_stat['home_score'] = play['home_score']
                player_stat['away_score'] = play['away_score']
                player_stat['winner'] = self.winner
                self.rows.append(player_stat)

    def stage_team_level_data(self, play, box_score):
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
                    aggregate_stats[team][field] += value
            aggregate_stats[team]['winner'] = winner
            aggregate_stats[team]['team'] = team
            aggregate_stats[team]['time'] = time
            aggregate_stats[team]['gameid'] = self.gameid
        self.aggregate_rows += aggregate_stats.values()

    def write_to_db(self):
        for row in tqdm(self.rows, desc="Writing Player Data"):
            self.individual_table.insert(row)
        for row in tqdm(self.aggregate_rows, desc="Writing Team Data"):
            self.team_table.insert(row)


if __name__ == '__main__':
    PlayByPlayToBoxScoreWriter(
        player_box_score_table, team_box_score_table,
        '400878160', debug=len(sys.argv) > 1).execute()
