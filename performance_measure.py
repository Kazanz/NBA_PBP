from collections import OrderedDict

from tqdm import tqdm


class PerformanceMeasureCaclulator(object):
    def __init__(self, stats):
        self.stats = stats
        self.set_game_totals(self.stats)

    def update_stats(self):
        for team, players in tqdm(self.stats.items(), desc="Added Perf Measures"):
            for player_stats in players:
                player_stats["PER"] = self.calculate_per(team, player_stats)
                player_stats["PIR"] = self.calculate_pir(player_stats)

    def set_game_totals(self, all_stats):
        if not all_stats:
            return
        self.team_stats = {}
        self.game_stats = {}
        for team, stats in all_stats.items():
            self.team_stats[team] = {}
            for player_stats in stats:
                for stat in player_stats.keys():
                    try:
                        value = float(player_stats[stat])
                    except (ValueError, TypeError):
                        continue
                    else:
                        self.team_stats[team].setdefault(stat, 0)
                        self.team_stats[team][stat] += value
                        self.game_stats.setdefault(stat, 0)
                        self.game_stats[stat] += value

    def calculate_per(self, team, stats):
        gm_AST = self.game_stats.get('AST', 0)
        gm_FG = self.game_stats.get('FGM', 1)
        gm_FGA = self.game_stats.get('FGA', 1)
        gm_FT = self.game_stats.get('FTM', 1)
        gm_FTA = self.game_stats.get('FTA', 1)
        gm_ORB = self.game_stats.get('OREB', 1)
        gm_PTS = self.game_stats.get('PTS', 0)
        gm_TOV = self.game_stats.get('TO', 0)
        gm_TRB = self.game_stats.get('TREB', 1)
        gm_PF = self.game_stats.get('PF', 1)
        tm_AST = self.team_stats[team].get('AST', 0)
        tm_FG = self.team_stats[team].get('FGM', 1)

        factor = (2.0 / 3.0) - (0.5 * (gm_AST / gm_FG)) \
            / (2.0 * (gm_FG / gm_FT))
        VOP = gm_PTS / (gm_FGA - gm_ORB + gm_TOV + 0.44 * gm_FTA)
        DRBP = (gm_TRB - gm_ORB) / gm_TRB

        min_multiplier = 1.0 / (stats.get('MIN', 1) or 1)
        assist_multiplier = 2.0 / 3.0 * stats.get('AST', 0)
        tm_assist_to_field_goal = (
            2.0 - factor * tm_AST / tm_FG) * stats.get('FGM', 0)
        tm_assist_to_free_throw = (
            .5 * stats.get('FTM', 0) * (2.0 - (1.0/3.0) * tm_AST / tm_FG)
        )
        personal_foul_stat = (stats.get('PF', 0) * (
            gm_FT/gm_PF - 0.44 * gm_FTA/gm_PF * VOP
        ))

        return min_multiplier * (
            stats.get('3PM', 0) + assist_multiplier + tm_assist_to_field_goal
            + tm_assist_to_free_throw - (VOP * stats.get('TO', 0))
            - (VOP * DRBP * (stats.get('FGA', 0) - stats.get('FGM', 0)))
            - (VOP * .44 * (.44 + (.56 * DRBP)) * (
                stats.get('FTA', 0) - stats.get('FTM', 0)
            ))
            + (VOP * (1.0 - DRBP) * (stats.get('DREB', 0)))
            + (VOP * DRBP * stats.get('OREB', 0)) + (VOP * stats.get('STL', 0))
            + (VOP * DRBP * stats.get('BLK', 0)) - personal_foul_stat
        )

    def calculate_pir(self, stats):
        return (
            stats.get('PTS', 0) + stats.get('AST', 0) + stats.get('STL', 0) +
            stats.get('BLK', 0) + stats.get('PFD', 0)
        ) - (
            stats.get('FGA', 0) + stats.get('FTA', 0) + stats.get('TO', 0) +
            stats.get('BLKD', 0) + stats.get('PF', 0)
        )


class PlayByPlayPerformanceMeasureCalculator(PerformanceMeasureCaclulator):
    def __init__(self, rows):
        self.rows = rows
        return super(PlayByPlayPerformanceMeasureCalculator, self).__init__({})

    def update_rows(self):
        new_rows = []
        for time, stats in tqdm(self.get_stats().items(), desc="Calculating Perf"):
            quarter, time = time.split(',')
            self.set_game_totals(stats)
            for row in self.rows:
                if row['quarter'] == int(quarter) and row['time'] == time:
                    row['uPER'] = self.calculate_per(row['team'], row)
                    row['PIR'] = self.calculate_pir(row)
                    new_rows.append(row)
        return new_rows

    def get_stats(self):
        last_quarter = None
        last_time = None
        time_stats = OrderedDict()
        stats = OrderedDict()
        for row in self.rows:
            quarter = row['quarter']
            time = row['time']
            team = row['team']
            if last_quarter is None:
                last_quarter = quarter
                last_time = time
            elif quarter != last_quarter or time != last_time:
                stats["{},{}".format(last_quarter, last_time)] = time_stats
                last_quarter = quarter
                last_time = time
                time_stats = {}
            time_stats.setdefault(team, [])
            time_stats[team].append(row)
        return stats
