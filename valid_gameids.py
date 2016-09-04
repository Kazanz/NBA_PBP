from playbyplay import make_soup


def team_links(year):
    url = "http://www.espn.com/nba/team/schedule/_/name/atl/year/{}/seasontype/2".format(year)
    soup = make_soup(url)
    options = soup.find('form', 'js-goto').find('select').findAll('option')
    return ["http://{}".format(option.attrs['value'].strip('/'))
            for option in options[1:]]


def game_ids(url):
    soup = make_soup(url)
    links = [li.find('a').attrs['href'].split('/')[-1]
             for li in soup.findAll("li", "score")]
    return set(links)


def get_all_game_ids():
    gameids = set()
    for year in range(2007, 2017):
        print(year)
        print("*" * 10)
        urls = team_links(year)
        for url in urls:
            print(url)
            gameids.update(game_ids(url))
        with open("gameids.txt", "a") as f:
            f.write(",".join(sorted(gameids)))
            f.write(",")
        gameids = set()


get_all_game_ids()
