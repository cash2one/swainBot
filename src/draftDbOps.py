import sqlite3
import re
from championinfo import championIdFromName,championNameFromId, convertChampionAlias, AliasException

regionsDict = {"North_America":"NA", "Europe":"EU", "LCK":"LCK", "LPL":"LPL",
                "LMS":"LMS"}
internationalEventsDict = {"Mid-Season_Invitational":"MSI",
                    "Rift_Rivals":"RR","World_Championship":"WRLDS"}
def getGameIdsByTournament(cursor, tournament):
    """
    getMatchIdsByTournament queries the connected db for game ids which match the
    input tournament string.

    Args:
        cursor (sqlite cursor): cursor used to execute commmands
        tournament (string): id string for tournament (ie "2017/Summer_Season/EU")
    Returns:
        gameIds (list(int)): list of gameIds
    """
    query = "SELECT id FROM game WHERE tournament=? ORDER BY id"
    params = (tournament,)
    cursor.execute(query, params)
    response = cursor.fetchall()
    vals = []
    for r in response:
        vals.append(r[0])
    return vals

def getMatchData(cursor, gameId):
    """
    getMatchData queries the connected db for draft data and organizes it into a more convenient
    format.

    Args:
        cursor (sqlite cursor): cursor used to execute commmands
        gameId (int): primary key of game to process
    Returns:
        match (dict): formatted pick/ban phase data for game
    """
    match = {"winner": None, "blue":{}, "red":{}}
    # Get winning team
    query = "SELECT winning_team FROM game WHERE id=?"
    params = (gameId,)
    cursor.execute(query, params)
    match["winner"] = cursor.fetchone()[0]

    # Get ban data
    query = "SELECT champion_id, selection_order FROM ban WHERE game_id=? and side_id=? ORDER BY selection_order"
    params = (gameId,0)
    cursor.execute(query, params)
    match["blue"]["bans"] = list(cursor.fetchall())

    query = "SELECT champion_id, selection_order FROM ban WHERE game_id=? and side_id=? ORDER BY selection_order"
    params = (gameId,1)
    cursor.execute(query, params)
    match["red"]["bans"] = list(cursor.fetchall())

    # Get pick data
    query = "SELECT champion_id, position_id, selection_order FROM pick WHERE game_id=? AND side_id=? ORDER BY selection_order"
    params = (gameId,0)
    cursor.execute(query, params)
    match["blue"]["picks"] = list(cursor.fetchall())

    query = "SELECT champion_id, position_id, selection_order FROM pick WHERE game_id=? AND side_id=? ORDER BY selection_order"
    params = (gameId,1)
    cursor.execute(query, params)
    match["red"]["picks"] = list(cursor.fetchall())

    return match

def getTournamentData(gameData):
    """
    getTournamentData cleans up and combines the region/season/split fields in gameData for entry into
    the game table. When combined with the game_id field it uniquely identifies the match played.
    The format of tournamentData output is 'year/split/region_abbrv' (forward slash delimiters)

    Args:
        gameData (dict): dictonary output from queryWiki()
    Returns:
        tournamentData (string): formatted and cleaned region/season/split data
    """
    if gameData["season"] is None:
        year = re.search("([0-9]+)",gameData["region"]).group(0)
    else:
        year = re.search("([0-9]+)",gameData["season"]).group(0)

    if gameData["split"] is None:
        tournamentData = internationalEventsDict["".join(re.split("_?[0-9]+_?",gameData["region"]))]
    else:
        tournamentData = "/".join([gameData["split"],regionsDict[gameData["region"]]])
    tournamentData = "/".join([year,tournamentData])
    return tournamentData

def getGameId(cursor,gameData):
    """
    getGameId looks in the game table for an entry with matching tournament and tourn_game_id as the input
    gameData and returns the id field. If no such entry is found, it adds this game to the game table and returns the
    id field.

    Args:
        cursor (sqlite cursor): cursor used to execute commmands
        gameData (dict): dictionary output from queryWiki()
    Returns:
        gameId (int): Primary key in game table corresponding to this gameData
    """
    tournament = getTournamentData(gameData)
    vals = (tournament,gameData["tourn_game_id"])
    gameId = None
    while gameId is None:
        cursor.execute("SELECT id FROM game WHERE tournament=? AND tourn_game_id=?", vals)
        gameId = cursor.fetchone()
        if gameId is None:
            print("Warning: Game not found. Attempting to add game.")
            err = insertGame(cursor,[game])
        else:
            gameId = gameId[0]
    return gameId

def insertGame(cursor, gameData):
    """
    insertGame attempts to format collected gameData from queryWiki() and insert
    into the game table in the competitiveGameData.db.

    Args:
        cursor (sqlite cursor): cursor used to execute commmands
        gameData (list(dict)): list of dictionary output from queryWiki()
    Returns:
        status (int): status = 1 if insert was successful, otherwise status = 0
    """
    status = 0
    assert isinstance(gameData,list), "gameData is not a list"
    for game in gameData:
        tournGameId = game["tourn_game_id"] # Which game this is within current split
        tournamentData = getTournamentData(game)

        # Check to see if game data is already in table
        vals = (tournamentData,tournGameId)
        cursor.execute("SELECT id FROM game WHERE tournament=? AND tourn_game_id=?", vals)
        result = cursor.fetchone()
        if result is not None:
            print("game {} already exists in table.. skipping".format(result[0]))
        else:
            # Get blue and red team_ids
            blueTeamId = None
            redTeamId = None
            while (blueTeamId is None or redTeamId is None):
                cursor.execute("SELECT id FROM team WHERE display_name=?",(game["blue_team"],))
                blueTeamId = cursor.fetchone()
                cursor.execute("SELECT id FROM team WHERE display_name=?",(game["red_team"],))
                redTeamId = cursor.fetchone()
                if (blueTeamId is None) or (redTeamId is None):
                    print("*WARNING: When inserting game-- team not found. Attempting to add teams")
                    err = insertTeam(cursor, [game])
                else:
                    blueTeamId = blueTeamId[0]
                    redTeamId = redTeamId[0]

            winner = game["winning_team"]
            vals = (tournamentData, tournGameId, blueTeamId, redTeamId, winner)
            cursor.execute("INSERT INTO game(tournament, tourn_game_id, blue_teamid, red_teamid, winning_team) VALUES(?,?,?,?,?)", vals)
    status = 1
    return status

def insertTeam(cursor, gameData):
    """
    insertTeam attempts to format collected gameData from queryWiki() and insert
    into the team table in the competitiveGameData.db.

    Args:
        cursor (sqlite cursor): cursor used to execute commmands
        wikiGameData (list(dict)): dictionary output from queryWiki()
    Returns:
        status (int): status = 1 if insert was successful, otherwise status = 0
    """
    status = 0
    assert isinstance(gameData,list), "gameData is not a list"
    for game in gameData:
        # We don't track all regions (i.e wildcard regions), but they can still appear at
        # international tournaments. When this happens we will track the team, but list their
        # region as NULL.
        if game["split"] is None:
            region = None
        else:
            region = regionsDict[game["region"]]
        teams = [game["blue_team"], game["red_team"]]
        for team in teams:
            vals = (region,team)
            cursor.execute("SELECT * FROM team WHERE display_name=?", (team,))
            result = cursor.fetchone()
            if result is None:
                cursor.execute("INSERT INTO team(region, display_name) VALUES(?,?)", vals)
    status = 1
    return status

def insertBan(cursor, gameData):
    """
    insertBan attempts to format collected gameData from queryWiki() and insert into the
    ban table in the competitiveGameData.db.

    Args:
        cursor (sqlite cursor): cursor used to execute commmands
        gameData (list(dict)): dictionary output from queryWiki()
    Returns:
        status (int): status = 1 if insert was successful, otherwise status = 0
    """
    status = 0
    assert isinstance(gameData,list), "gameData is not a list"
    teams = ["blue", "red"]
    for game in gameData:
        tournament = getTournamentData(game)
        vals = (tournament,game["tourn_game_id"])
        gameId = getGameId(cursor,game)
        # Check for existing entries in table. Skip if they already exist.
        cursor.execute("SELECT game_id FROM ban WHERE game_id=?",(gameId,))
        result = cursor.fetchone()
        if result is not None:
            print("Bans for game {} already exists in table.. skipping".format(result[0]))
        else:
            for k in range(len(teams)):
                bans = game["bans"][teams[k]]
                selectionOrder = 0
                side = k
                for ban in bans:
                    if ban == "none":
                        # Special case if no ban was submitted in game
                        banId = None
                    else:
                        banId = championIdFromName(ban)
                        # If no such champion name is found, try looking for an alias
                        if banId is None:
                            banId = championIdFromName(convertChampionAlias(ban))
                    selectionOrder += 1
                    vals = (gameId,banId,selectionOrder,side)
                    cursor.execute("INSERT INTO ban(game_id, champion_id, selection_order, side_id) VALUES(?,?,?,?)", vals)
    status = 1
    return status

def insertPick(cursor, gameData):
    """
    insertPick formats collected gameData from queryWiki() and inserts it into the pick table of the
    competitiveGameData.db.

    Args:
        cursor (sqlite cursor): cursor used to execute commmands
        gameData (list(dict)): list of formatted game data from queryWiki()
    Returns:
        status (int): status = 1 if insert was successful, otherwise status = 0
    """
    status = 0
    assert isinstance(gameData,list), "gameData is not a list"
    teams = ["blue", "red"]
    for game in gameData:
        tournament = getTournamentData(game)
        vals = (tournament,game["tourn_game_id"])
        gameId = getGameId(cursor,game)
        # Check for existing entries in table. Skip if they already exist.
        cursor.execute("SELECT game_id FROM pick WHERE game_id=?",(gameId,))
        result = cursor.fetchone()
        if result is not None:
            print("Picks for game {} already exists in table.. skipping".format(result[0]))
        else:
            for k in range(len(teams)):
                picks = game["picks"][teams[k]]
                selectionOrder = 0
                side = k
                for (pick,position) in picks:
                    if pick == "none":
                        # Special case if no pick was submitted to game (not really sure what that would mean
                        # but being consistent with insertPick())
                        pickId = None
                    else:
                        pickId = championIdFromName(pick)
                        # If no such champion name is found, try looking for an alias
                        if pickId is None:
                            #print(json.dumps(game, indent=4, sort_keys=True))
                            pickId = championIdFromName(convertChampionAlias(pick))
                    selectionOrder += 1
                    vals = (gameId,pickId,position,selectionOrder,side)
                    cursor.execute("INSERT INTO pick(game_id, champion_id, position_id, selection_order, side_id) VALUES(?,?,?,?,?)", vals)
    status = 1
    return status