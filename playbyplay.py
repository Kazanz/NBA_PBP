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


class PlayByPlayToBoxScoreWriter(object):
    """Create a running boxscore from play by play data and write it to a db."""

    def __init__(self, table, gameid):
        self.table = table
        self.gameid = gameid
        self.pbp_data = get_play_by_play(gameid)
        self.running_box_score = {}

    #TODO: Still needs to track play time for each player.
    def execute(self):
        for play in self.pbp_data:
            play_stats = self.play_to_stats(play['play'])
            if not play_stats:
                print("No stat for: {}".format(play['play']))
            else:
                team = play['team']
                self.running_box_score.setdefault(team, {})
                for player, stats in play_stats.items():
                    if player not in self.running_box_score[team]:
                        self.running_box_score[team][player] = stats
                    else:
                        for stat, amount in stats.items():
                            self.running_box_score[team][player].setdefault(
                                stat, amount)
                            self.running_box_score[team][player][stat] += amount
                self.commit_to_db(play, self.running_box_score)

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

    def play_to_stats(self, play):
        for method in METHODS:
            stats = method(play)
            if stats:
                return stats


if __name__ == '__main__':
    PlayByPlayToBoxScoreWriter(player_box_score_table, '400878160').execute()
