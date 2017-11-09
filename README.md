# NBA_PBP

This was the data scraping algorithm used in the paper *Predicting NBA games in realtime: A data snapshot approach* which won best paper award for technical prototype at the 2016 Workshop on Information Technology & Systems (WITS).

The university press release can be found here: http://www.usf.edu/business/news/articles/161221-wits-conference.aspx

# Overview

These scripts scrape ESPN's play-by-play data to get the real-time box scores at the time of each play in the game.
Additionally it two performance measures for each player: **Unadjusted Player Effeciency Rating (uPER)** and **Performance Index Rating (PIR)**.

Two tables are created `team_box_score` for the aggregate stats for each team and `player_box_score` for the individuals players box scores.

# Usage

## Setup

1. `git clone git@github.com:Kazanz/NBA_PBP.git`
2. `virtualenv nba_pbp` (optional)
3. `source nba_php/bin/activate` (optional)
4. `pip install -r reqs.txt`

### Database connection

By default this will connect to/create a sqlite3 `demo.db` database in the current working directory.
You can override this functionality by setting the `NBA_DB_URI` environment variable.

Ex: `export NBA_DB_URI="mysql://user:pass@host/db"`

## Realtime data

Gets the realtime data from [NBA Starting Five](nbastartingfive.com).  Defaults to Game 7 of the 2016 NBA finals between Cleveland and Goldenstate.

### Usage

1. `python realtime.py`

## Historical Play-by-Play data

Gets historical data from [ESPN](http://www.espn.com/nba/playbyplay?gameId=400878160&period=2#gp-quarter-2).  Defaults to Game 7 of the 2016 NBA finals between Cleveland and Goldenstate.

### Usage

`python playbyplay.py`

### Debuggging

Not all play-by-play data is relevant to the box scores so some are skipped. To see what plays are being skipped by the script run:

`python playbyplay.py debug`
