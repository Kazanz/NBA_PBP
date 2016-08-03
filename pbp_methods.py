import re
from collections import OrderedDict


def get_player(play):
    return " ".join(play.split(' ')[:2]).strip()


def add_drawn_foul(play):
    matches = re.findall('\(.*?draws the foul\)', play)
    if matches:
        return {matches[0][1:-16]: {'PFD': 1}}
    return {}


def add_assist(play):
    matches = re.findall('\(.*?assists\)', play)
    if matches:
        return {matches[0][1:-9]: {'AST': 1}}
    return {}


def add_blocked(play):
    matches = re.findall(" .*? .*?'s shot", play)
    if matches:
        return {matches[0][1:-7]: {'FGA': 1, 'BLKD': 1}}
    return {}


def add_steals(play):
    matches = re.findall('\(.*?steals\)', play)
    if matches:
        return {matches[0][1:-8]: {'STL': 1}}
    return {}


def other_player_stats(stats, play):
    """Add stats for other players in the play."""
    data = {}
    if stats.get('PTS') and not stats.get("FTA"):
        data = add_assist(play)
    elif stats.get('BLK'):
        data = add_blocked(play)
    elif stats.get('TO'):
        data = add_steals(play)
    elif stats.get('PF'):
        data = add_drawn_foul(play)
    return data


def add_player(f):
    def inner(play):
        stats = f(play)
        if stats:
            data = OrderedDict({get_player(play): stats})
            other_player_data = other_player_stats(stats, play)
            if other_player_data:
                data.update(other_player_data)
            return data
    return inner


@add_player
def freethrow(play):
    if re.findall('free throw', play):
        if re.findall('misses', play):
            return {"FTA": 1}
        elif re.findall('makes', play):
            return {"FTA": 1, "FTM": 1, "PTS": 1}


@add_player
def twopoint(play):
    match = re.findall('jumper', play) and not re.findall('three point', play)
    if not match:
        matches = ['two point shot', 'dunk', 'layup', 'putback', 'hook shot',
                   'tip shot', 'Regular Jump Shot',]
        for expr in matches:
            match = re.findall(expr, play)
            if match:
                break
    if match:
        if re.findall('misses', play):
            return {"FGA": 1}
        elif re.findall('makes', play):
            return {"FGA": 1, "FGM": 1, "PTS": 2}


@add_player
def threepoint(play):
    if re.findall('three point', play):
        if re.findall('misses', play):
            return {"FGA": 1, '3PA': 1}
        elif re.findall('makes', play):
            return {"FGA": 1, "FGM": 1, "3PA": 1, "3PM": 1,  "PTS": 3}


@add_player
def rebound(play):
    if re.findall('rebound', play):
        # An unknown rebound that cannot be attributed to any player.
        if play.split(' ')[1] in ['offensive', 'defensive']:
            return
        if re.findall('offensive', play):
            return {"OREB": 1, "TREB": 1}
        elif re.findall('defensive', play):
            return {"DREB": 1, "TREB": 1}


@add_player
def block(play):
    if re.findall('blocks', play):
        return {'BLK': 1}


@add_player
def foul(play):
    if re.findall('foul', play):
        return {'PF': 1}


@add_player
def turnover(play):
    if re.findall('turnover', play) or re.findall('Turnover', play) \
            or re.findall("bad pass", play):
        return {'TO': 1}


METHODS = [freethrow, twopoint, threepoint, rebound, block, foul, turnover]
