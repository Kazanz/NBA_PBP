# NBA_PBP
Extracts real-time NBA boxscores and calculates each players uPER at that point in the game.

This is a proff of concept.  We can scrape real-time player scores of nba games and calculate the unadjusted player effeciency rating (uPER)
of each player at that time in the game.

# Usage

1. `git clone git@github.com:Kazanz/NBA_PBP.git`
2. `virtualenv nba_pbp` (optional)
3. `pip install -r reqs.txt`
4. `python nba_etl.py`


# Next Steps

## Collect previous play-by-play data

Collect previous play-by-play box score data needed to create predictive models.
Data will be collected from `scores.espn.go.com`.  A "special" scraper must be developed that can interpret play-by-play text.
Such as "Lebron James misses a free throw attempt."

This data will then be loaded into a database, and the real-time scraper can make predictions against the database or scrape
directly into the database and another tool can handle developing predictions.
