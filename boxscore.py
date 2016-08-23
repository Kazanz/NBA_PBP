from playbyplay import make_soup

def get_point_diff(gameid):
    """Positive point diff favors home, negative away."""
    url = "http://espn.go.com/nba/playbyplay?gameId={}".format(gameid)
    divs = make_soup(url).findAll("div", "score-container")
    away_score, home_score = map(int, [div.text for div in divs])
    return home_score - away_score

print(get_point_diff('400878160'))
