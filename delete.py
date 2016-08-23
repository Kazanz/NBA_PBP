def predict_winner(gameid):
    pointdiff = get_point_diff(gameid)
    period, time = get_period_time(gameid)
    home_win_prob = calc_home_team_win_prob(period, time, abs(pointdiff)) * 100
    away_win_prob = 100 - home_win_prob
    home, away = get_home_away_teams(gameid)
    msg = "#NBAFinals Winning Probabilities as of {}-Q{} #{}: {}% #{}: {}%"
    msg = msg.format(time, period, home, home_win_prob, away, away_win_prob)
    post_to_twitter(msg)
