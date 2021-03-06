import os

import dataset


__all__ = ["db", "per_table", "player_box_score_table"]


db = dataset.connect(os.getenv("NBA_DB_URI", 'sqlite:///demo6.db'))
per_table = db['PER_data']
player_box_score_table = db['player_box_score']
team_box_score_table = db['team_box_score']
game_table = db['game_data']
