"""DATA is from NBAstuffers.net"""
import re
import string
from urllib import urlencode

import click
import requests
from bs4 import BeautifulSoup


@click.group()
def cmds():
    pass


@cmds.command()
@click.option('--csv', help='CSV file to extract stats from.')
def write_stats(csv):



def read_csv

#def scrape_per_from_nbastartingfive():
#    for pos in ["PG", "SG", "SF", "PF", "C"]:
#        url = "http://www.nbastartingfive.com/ajaxLiveStats.jsp?"
#        url += urlencode({"id": 3, "pos": pos})  # id 3 == NBA.
#        html = get_html(url)
#        soup = BeautifulSoup(html)
#        stats = extract_player_stats(soup)
#        write_stats_to_db(stats)
#
#
#def get_html(url):
#    result = requests.get(url)
#    if not result.ok:
#        print("Error making request: {}".format(result.status_code))
#        click.abort()
#    return result.content
#
#
#def extract_player_stats(soup):
#    stats = []
#    rows = soup.findAll('tr')[1:]
#    mappings = [col.span.text for col in rows[0].findAll('td')]
#    print(mappings)
#    for row in rows[1:]:
#        player_stats = {}
#        for i, col in enumerate(row.findAll('td')):
#            stat = mappings[i]
#            if i == 0:
#                player_stats[stat] = extract_team_name(col)
#            else:
#                player_stats[stat] = float(col.text.split('-')[0])
#        stats.append(player_stats)
#    grouped_stats = group_teams(stats)
#    return add_per(grouped_stats)
#
#
#def group_teams(stats):
#    grouped = {}
#    for stat in stats:
#        name = stat['NAME']
#        grouped.setdefault(name, [])
#        grouped[name].append(stat)
#    return grouped
#
#
#def add_per(grouped_stats):
#    for k, v in grouped_stats.values():
#        for player_stats in v:
#            player_stats["PER"] = calculate_per(player_stats, v
#
#
#
#def write_steps_to_db():
#    pass


def calculate_per(stats):
    min_multiplier = 1 / stats['MIN']
    assist_multiplier = 2.0 / 3.0 * stats['AST']
    import pdb; pdb.set_trace()
    pass


def extract_team_name(col):
    image_name = col.img.attrs['src'].split('/')[-1].split('.')[0]
    return re.findall(r'[A-Za-z]+', str(image_name))[0]


if __name__ == "__main__":
    calc_per()
