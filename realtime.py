"""DATA is from NBAstatingfive.com"""
import re
from urllib import urlencode


import requests
from bs4 import BeautifulSoup

from db import per_table
from per import PERCaclulator


def write_data(stats):
    for data in stats.values():
        per_table.insert_many(data)


def get_scores():
    # TODO: add args to limit by specific teams necessary for proper game
    # stats.  Home + Away args.

    stats = {}
    for pos in ["PG", "SG", "SF", "PF", "C"]:
        for team, players in extract_player_stats(pos).items():
            if team not in stats:
                stats[team] = []
            stats[team] += players
    return add_per(stats)


def extract_player_stats(pos):
    stats = []
    html = get_html(pos)
    rows = BeautifulSoup(html, "html.parser").findAll('tr')[1:]
    mappings = [col.span.text for col in rows[0].findAll('td')]
    gametime = get_gametime()
    for row in rows[1:]:
        player_stats = get_player_stats(mappings, row)
        player_stats['gametime'] = gametime
        stats.append(player_stats)
    grouped_stats = group_teams(stats)
    return grouped_stats


def get_html(pos):
    url = "http://www.nbastartingfive.com/ajaxLiveStats.jsp?"
    url += urlencode({"id": 3, "pos": pos})  # id 3 == NBA.
    result = requests.get(url)
    if not result.ok:
        print("Error making request: {}".format(result.status_code))
        raise RuntimeError("Cannot reach nbastartingfive.com.")
    return result.content


def get_player_stats(mappings, row):
    player_stats = {}
    for i, col in enumerate(row.findAll('td')):
        stat = str(mappings[i])
        if i == 0:
            team_name, player_name = extract_names(col)
            player_stats['TEAM'] = team_name
            player_stats[stat] = player_name
        else:
            text = col.text.split('-')
            player_stats[stat] = float(text[0])
            if len(text) > 1:
                stat = stat[:-1] + "A"  # Turns FGM to FGA.
                player_stats[stat] = float(text[1])
    return player_stats


def group_teams(stats):
    grouped = {}
    for stat in stats:
        name = stat['TEAM']
        grouped.setdefault(name, [])
        grouped[name].append(stat)
    return grouped


def extract_names(col):
    image_name = col.img.attrs['src'].split('/')[-1].split('.')[0]
    return (re.findall(r'[A-Za-z]+', str(image_name))[0], col.text.strip())


def add_per(grouped_stats):
    calc = PERCaclulator(grouped_stats)
    calc.update_stats()
    return calc.stats


def get_gametime():
    """Currently not implemented.  Will implement later."""
    return "Q1 - 12:00"


if __name__ == "__main__":
    write_data(get_scores())
