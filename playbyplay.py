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
    player_times = {}
    players_in_game = {}

    def is_substitution(self, play, quarter, time):
        if re.findall('enters the game for', play):
            player1, player2 = play.split(" enters the game for ")
            self.players_in_game[player1] = {'quarter': quarter, 'time': time}
            self._update_player_time(player2, quarter, time, entering=False)
            del self.players_in_game[player2]

    def update_time(self, player, time, stats):
        pass

    def _update_player_time(self, player, quarter, time, entering):
        in_min, in_sec = map(int, self.players_in_game.split(':'))
        out_min, out_sec = map(int, time.split(':'))
        play_time = 0

        if player not in self.player_times:  # Is a starter and first sub out.
            play_time = (quarter - 1) * 12 if quarter > 1 else 0
            play_time += int(out_min)
        else:
            quarter_diff = quarter - self.players_in_game[player]['quarter']
            if quarter_diff >= 2:
                play_time += (quarter_diff - 1) * 12
            if quarter_diff >= 1:
                play_time += in_min
            if quarter_diff == 0:
                play_time += in_min - out_min
            else:
                quarter_length_min = 12 if quarter <= 4 else 5
                play_time += quarter_length_min - out_min
            # Seconds adjustment.
            play_time += 1 if 60 - out_sec + in_sec >= 60 else -1

        player_time = self.player_times.setdefault(player, 0)
        player_time += play_time
        self.player_times[player] = play_time


class PlayByPlayToBoxScoreWriter(object):
    """Create a running boxscore from play by play data and write it to a db."""

    def __init__(self, table, gameid):
        self.table = table
        self.gameid = gameid
        self.pbp_data = get_play_by_play(gameid)
        self.running_box_score = {}
        self.subtracker = SubstitutionTracker()

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
        print("No stat for: {}".format(play))

    def update_player_stats(self, team, play, play_stats):
        for player, stats in play_stats.items():
            import pdb; pdb.set_trace();
            stats['MIN'] = self.get_time(play, player, stats)
            if player not in self.running_box_score[team]:
                self.running_box_score[team][player] = stats
            else:
                self.update_running_box_score(team, player, stats)

    def get_time(self, play, player, stats):
        self.subtracker.is_substitution(play)
        self.subtracker.update_times(play['time'])

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
