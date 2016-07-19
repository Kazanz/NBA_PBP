"""DATA is from NBAstatingfive.com"""
import re
from urllib import urlencode


import dataset
import requests
from bs4 import BeautifulSoup


def write_data(stats):
    db = dataset.connect('sqlite:///demo.db')
    table = db['PER_data']
    for data in stats.values():
        table.insert_many(data)


class PERCaclulator(object):
    def __init__(self, stats):
        self.stats = stats
        self.set_game_totals()

    def update_stats(self):
        for team, players in self.stats.items():
            for player_stats in players:
                player_stats["PER"] = self.calculate_per(team, player_stats)

    def set_game_totals(self):
        self.team_stats = {}
        self.game_stats = {}
        for team, stats in self.stats.items():
            self.team_stats[team] = {}
            for player_stats in stats:
                for stat in player_stats.keys():
                    try:
                        value = float(player_stats[stat])
                    except ValueError:
                        continue
                    else:
                        self.team_stats[team].setdefault(stat, 0)
                        self.team_stats[team][stat] += value
                        self.game_stats.setdefault(stat, 0)
                        self.game_stats[stat] += value

    def calculate_per(self, team, stats):
        gm_AST = self.game_stats['AST']
        gm_FG = self.game_stats['FGM']
        gm_FGA = self.game_stats['FGA']
        gm_FT = self.game_stats['FTM']
        gm_FTA = self.game_stats['FTA']
        gm_ORB = self.game_stats['OREB']
        gm_PTS = self.game_stats['PTS']
        gm_TOV = self.game_stats['TO']
        gm_TRB = self.game_stats['TREB']
        gm_PF = self.game_stats['PF']
        tm_AST = self.team_stats[team]['AST']
        tm_FG = self.team_stats[team]['FGM']
        tm_FG = self.team_stats[team]['FGM']

        factor = (2.0 / 3.0) - (0.5 * (gm_AST / gm_FG)) \
            / (2.0 * (gm_FG / gm_FT))
        VOP = gm_PTS / (gm_FGA - gm_ORB + gm_TOV + 0.44 * gm_FTA)
        DRBP = (gm_TRB - gm_ORB) / gm_TRB

        min_multiplier = 1.0 / stats['MIN']
        assist_multiplier = 2.0 / 3.0 * stats['AST']
        tm_assist_to_field_goal = (
            2.0 - factor * tm_AST / tm_FG) * stats['FGM']
        tm_assist_to_free_throw = (
            .5 * stats['FTM'] * (2.0 - (1.0/3.0) * tm_AST / tm_FG)
        )
        personal_foul_stat = (stats['PF'] * (
            gm_FT/gm_PF - 0.44 * gm_FTA/gm_PF * VOP
        ))

        return min_multiplier * (
            stats['3PM'] + assist_multiplier + tm_assist_to_field_goal
            + tm_assist_to_free_throw - (VOP * stats['TO'])
            - (VOP * DRBP * (stats['FGA'] - stats['FGM']))
            - (VOP * .44 * (.44 + (.56 * DRBP)) * (stats['FTA'] - stats['FTM']))
            + (VOP * (1.0 - DRBP) * (stats['DREB']))
            + (VOP * DRBP * stats['OREB']) + (VOP * stats['STL'])
            + (VOP * DRBP * stats['BLK']) - personal_foul_stat
        )


class RTBoxScores(object):
    @staticmethod
    def get_scores():
        # TODO: add args to limit by specific teams necessary for proper game
        # stats.  Home + Away args.

        stats = {}
        for pos in ["PG", "SG", "SF", "PF", "C"]:
            for team, players in RTBoxScores.extract_player_stats(pos).items():
                if team not in stats:
                    stats[team] = []
                stats[team] += players
        return RTBoxScores.add_per(stats)

    @staticmethod
    def extract_player_stats(pos):
        stats = []
        html = RTBoxScores.get_html(pos)
        rows = BeautifulSoup(html, "html.parser").findAll('tr')[1:]
        mappings = [col.span.text for col in rows[0].findAll('td')]
        gametime = RTBoxScores.get_gametime()
        for row in rows[1:]:
            player_stats = RTBoxScores.get_player_stats(mappings, row)
            player_stats['gametime'] = gametime
            stats.append(player_stats)
        grouped_stats = RTBoxScores.group_teams(stats)
        return grouped_stats

    @staticmethod
    def get_html(pos):
        url = "http://www.nbastartingfive.com/ajaxLiveStats.jsp?"
        url += urlencode({"id": 3, "pos": pos})  # id 3 == NBA.
        result = requests.get(url)
        if not result.ok:
            print("Error making request: {}".format(result.status_code))
            raise RuntimeError("Cannot reach nbastartingfive.com.")
        return result.content

    @staticmethod
    def get_player_stats(mappings, row):
        player_stats = {}
        for i, col in enumerate(row.findAll('td')):
            stat = str(mappings[i])
            if i == 0:
                team_name, player_name = RTBoxScores.extract_names(col)
                player_stats['TEAM'] = team_name
                player_stats[stat] = player_name
            else:
                text = col.text.split('-')
                player_stats[stat] = float(text[0])
                if len(text) > 1:
                    stat = stat[:-1] + "A"  # Turns FGM to FGA.
                    player_stats[stat] = float(text[1])
        return player_stats

    @staticmethod
    def group_teams(stats):
        grouped = {}
        for stat in stats:
            name = stat['TEAM']
            grouped.setdefault(name, [])
            grouped[name].append(stat)
        return grouped

    @staticmethod
    def extract_names(col):
        image_name = col.img.attrs['src'].split('/')[-1].split('.')[0]
        return (re.findall(r'[A-Za-z]+', str(image_name))[0], col.text.strip())

    @staticmethod
    def add_per(grouped_stats):
        calc = PERCaclulator(grouped_stats)
        calc.update_stats()
        return calc.stats

    @staticmethod
    def get_gametime():
        """Currently not implemented.  Will implement later."""
        return "Q1 - 12:00"


if __name__ == "__main__":
    write_data(RTBoxScores.get_scores())
