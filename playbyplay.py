import re

from bs4 import BeautifulSoup
from urllib2 import urlopen

from db import player_box_score_table
from pbp_methods import METHODS
from per import PERCaclulator


ESPN_URL = "http://scores.espn.go.com"


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

    print("Gettting play-by-play for game: {}".format(gameid))

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
    return data


class SubstitutionTracker(object):
    """Keeps track of minutes played in the play-by-play for each player."""
    seconds_played_by_player = {}
    players_in_game = []
    last_quarter = 1
    last_time = "12:00"

    def __init__(self, gameid):
        self._set_starters(gameid)

    @property
    def players_minutes(self):
        return {k: (v % 60) for k, v in self.seconds_played_by_player.items()}

    def make_substitution(self, play):
        if re.findall('enters the game for', play):
            player1, player2 = play.split(" enters the game for ")
            self.players_in_game.append(player1)
            self.players_in_game.remove(player2)
            self.seconds_played_by_player.setdefault(player1, 0)
            print("SUB", player1, player2)
            return True

    def update_minutes_played(self, quarter, time):
        seconds_elapsed = self._seconds_elapsed(quarter, time)
        for player in self.players_in_game:
            self.seconds_played_by_player.setdefault(player, 0)
            self.seconds_played_by_player[player] += seconds_elapsed

    def _seconds_elapsed(self, quarter, time):
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
    """Create a running boxscore from play by play data and write it to a db.

    Not play-by-play does not always provide the player who got a rebound
    when the rebound is shared by many players, therfore total box scores
    could be off by a couple rebounds.
    """

    def __init__(self, table, gameid):
        self.table = table
        self.gameid = gameid
        self.pbp_data = get_play_by_play(gameid)
        self.running_box_score = {}
        self.subtracker = SubstitutionTracker(gameid)

    def execute(self):
        for play in self.pbp_data:
            play_stats = self.play_to_stats(play['play'])
            if play_stats:
                team = play['team']
                self.running_box_score.setdefault(team, {})
                self.update_player_stats(team, play, play_stats)
                self.commit_to_db(play, self.running_box_score)

    def play_to_stats(self, play):
        for method in METHODS:
            stats = method(play)
            if stats:
                return stats
        if not self.subtracker.make_substitution(play):
            print("No stat for: {}".format(play))

    def update_player_stats(self, team, play, play_stats):
        for player, stats in play_stats.items():
            stats['MIN'] = self.get_time(play, player)
            if player not in self.running_box_score[team]:
                self.running_box_score[team][player] = stats
            else:
                self.update_running_box_score(team, player, stats)

    def get_time(self, play, player):
        self.subtracker.update_minutes_played(play['quarter'], play['time'])
        return self.subtracker.players_minutes[player]

    def update_running_box_score(self, team, player, stats):
        for stat, amount in stats.items():
            self.running_box_score[team][player].setdefault(stat, amount)
            self.running_box_score[team][player][stat] += amount

    def commit_to_db(self, play, box_score):
        """Write the box score to the database."""
        stats = self.format_box_score_for_per_calc(play, box_score)
        calc = PERCaclulator(stats)
        calc.update_stats()
        for stats in calc.stats.values():
            for player_stat in stats:
                self.table.insert(player_stat)

    def format_box_score_for_per_calc(self, play, box_score):
        stats = {}
        for team, players_stats in box_score.items():
            stats.setdefault(team, [])
            for player, player_stats in players_stats.items():
                player_stats['player'] = player
                player_stats['team'] = team
                player_stats['time'] = play['time']
                player_stats['quarter'] = play['quarter']
                player_stats['is_home'] = play['home']
                stats[team].append(player_stats)
        return stats

if __name__ == '__main__':
    PlayByPlayToBoxScoreWriter(player_box_score_table, '400878160').execute()
