# NBA_PBP
Extracts real-time NBA boxscores and calculates each players uPER at that point in the game.

This is a proff of concept.  We can scrape real-time player scores of nba games and calculate the unadjusted player effeciency rating (uPER)
of each player at that time in the game.

# Usage

## Setup

1. `git clone git@github.com:Kazanz/NBA_PBP.git`
2. `virtualenv nba_pbp` (optional)
3. `pip install -r reqs.txt`

### Database connection

By default this will connect to/create a sqlite3 `demo.db` database in the current working directory.
You can override this by settings the `NBA_DB_URI` environment variable.  *May require additinoal packages or drivers*.

Ex: `export NBA_DB_URI="mysql://user:pass@host/db"`

## Realtime data

This currently writes the realtime boxscore and uPER of each player data from the end of game 7 of the NBA finals between Cleveland and Goldenstate
to the `PER_data` table.

1. `python realtime.py`

## Historical Play-by-Play data

This gets each player's box score as well as their uPER for each moment of the game covered by the play-by-play on `espn.go.com` and saves it to
the `player_box_score` table. By default it also does Game 7 of the finals, but can be easily automated to get historical records for each game
over the last decade. *It would take two lines of code, but would take a while, so we need to decide how far back this study should go.*

`python playbyplay.py`

*Note: This still does not acquire players minutes at that point in the game so the uPER is not quite accurate.
I need a slightly more complicated algorithm to extract that info from the play-by-play
but it shouldn't take more than a couple hours.*

### Debuggging

See what plays are being skipped by the script.

`python playbyplay.py debug`
