import requests
import json
import sys
import argparse
import os
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
apikey = os.getenv("JELLYFIN_API_KEY")
jellyfin_url = os.getenv("JELLYFIN_URL")


def backup(username):
    usersurl = f"http://{jellyfin_url}:8096/Users"
    users = requests.get(usersurl, params={"apikey": apikey})
    if users.status_code == 401:
        print("Invalid API key")
        sys.exit(1)
    users = users.json()
    userid = None
    for user in users:
        if user['Name'] == username:
            userid = user['Id']
            break

    if not userid:
        print(f"User {username} not found!")
        sys.exit(1)
    user = requests.get(f"http://{jellyfin_url}:8096/Users/{userid}", params={"apikey": apikey, "userId": userid})
    username = user.json()['Name']

    output = {
        "username": username,
        "backupdate": datetime.now().isoformat(),
        "items": []
    }
    baseurl=f"http://{jellyfin_url}:8096/Items"
    params={"apikey": apikey,
        "userId": userid,
        "isPlayed": True,
        "recursive": True}
    r = requests.get(baseurl, params=params)
    data_played = r.json()

    params={"apikey": apikey,
        "userId": userid,
        "isFavorite": True,
        "recursive": True}
    r = requests.get(baseurl, params=params)
    data_favorited = r.json()

    data = {"Items": []}
    for item in data_played['Items']:
        data["Items"].append(item)
    for item in data_favorited['Items']:
        isin = False
        for item2 in data['Items']:
            if item['Id'] == item2['Id']:
                isin = True
        if not isin:
            data["Items"].append(item)

    favoritepeople = f"http://{jellyfin_url}:8096/Persons"
    params = {"Recursive": True,
    "IsFavorite": True,
    "userId": userid,
    "apikey": apikey}
    fp = requests.get(favoritepeople, params=params)
    data_favorited_people = fp.json()
    for item in data_favorited_people['Items']:
        outputitem = {"Type": item['Type'],
        "Name": item['Name'],
        "IsFavorite": True,
        }
        output["items"].append(outputitem)

    for item in data['Items']:
        outputitem = {"Type": item['Type'],
        "Name": item['Name'],
        "Played": item['UserData']['Played'],
        "IsFavorite": item['UserData']['IsFavorite'],
        }
        itemid = item['Id']
        if item['LocationType'] == "Virtual":
            continue
        pathrequest = requests.get(f"http://{jellyfin_url}:8096/Users/{userid}/Items/{itemid}", params={"apikey": apikey, "userId": userid})
        pathdata = pathrequest.json()

        imdbid, tmdbid, tvdbid = None, None, None
        imdbid = pathdata.get('ProviderIds', {}).get('Imdb')
        tmdbid = pathdata.get('ProviderIds', {}).get('Tmdb')
        tvdbid = pathdata.get('ProviderIds', {}).get('Tvdb')
        if imdbid:
            outputitem['imdbid'] = imdbid
        if tmdbid:
            outputitem['tmdbid'] = tmdbid
        if tvdbid:
            outputitem['tvdbid'] = tvdbid
        if item["Type"] == "Episode":
            outputitem['SeriesName'] = item['SeriesName']
            outputitem['SeasonName'] = item['SeasonName']

        else:
            output["items"].append(outputitem)
            continue
        output["items"].append(outputitem)
    with open("jellyfin.json", "w") as f:
        f.write(json.dumps(output))
def restore(dryrun=False):

    with open("jellyfin.json", "r") as f:
        data = f.read()

    data = json.loads(data)
    username = data["username"]
    print(f"Restoring {len(data['items'])} items for {username} from {data['backupdate']}...")
    usersurl = f"http://{jellyfin_url}:8096/Users"
    users = requests.get(usersurl, params={"apikey": apikey})
    if users.status_code == 401:
        print("Invalid API key")
        sys.exit(1)
    users = users.json()
    for user in users:
        if user['Name'] == username:
            userid = user['Id']
            break
    if not userid:
        print(f"User {username} not found")

    baseurl=f"http://{jellyfin_url}:8096/Items"
    params={"apikey": apikey,
        "userId": userid,
        "recursive": True,
        "excludeItemTypes": "Photo",
        }
    r = requests.get(baseurl, params=params)
    all_items = r.json()
    people = {}
    for i in all_items['Items']:
            url = f"http://{jellyfin_url}:8096/Users/{userid}/Items/{i['Id']}"
            params = {"apikey": apikey,
                "userId": userid}
            r = requests.get(url, params=params)
            try:
                requesteditem = r.json()
            except: #item is missing
                pass
            for p in requesteditem['People']:
                people[p['Name']] = p['Id']
    for person, id in people.items():
        all_items['Items'].append({"Name": person, "Type": "Person", "Id": id})

    for item in data['items']:
        if item['Type'] == "Person":
            found_item = item_search(all_items, "Person", name=item['Name'])
        elif item['Type'] == "Episode" or item['Type'] == "Movie":
            found_item = item_search(all_items, item['Type'], name=item.get('Name'), series_name=item.get('SeriesName'), season_name=item.get('SeasonName'), imdbid=item.get('imdbid'), tmdbid=item.get('tmdbid'), tvdbid=item.get('tvdbid'))
        if found_item:
            favorite_url = f"http://{jellyfin_url}:8096/Users/{userid}/FavoriteItems/{found_item['Id']}"
            favorite_params = {"apikey": apikey,
                "userId": userid,
                "IsFavorite": item['IsFavorite'],
                "isPlayed": item.get('Played', False)}
            if item['IsFavorite']:
                if not dryrun:
                    requests.post(favorite_url, params=favorite_params)
            if found_item['Type'] != "Person":
                played_url = f"http://{jellyfin_url}:8096/Users/{userid}/PlayedItems/{found_item['Id']}"
                played_params = {"apikey": apikey,
                    "userId": userid,
                    "IsPlayed": item['Played']}
                if not dryrun:
                    requests.post(played_url, params=played_params)
        else:
            print(f"Failed to restore {item['Type']} {item['Name']}")

def item_search(items, type, name=None, series_name=None, season_name=None, imdbid=None, tmdbid=None, tvdbid=None):
    for item in items['Items']:
        if 'Type' in item and item['Type'] != type:
            continue
        if name and 'Name' in item and item['Name'].lower() != name.lower():
            continue
        if series_name and 'SeriesName' in item and item['SeriesName'].lower() != series_name.lower():
            continue
        if season_name and 'SeasonName' in item and item['SeasonName'].lower() != season_name.lower():
            continue
        if imdbid and 'ProviderIds' in item and item['ProviderIds']['Imdb'] != imdbid:
            continue
        if tmdbid and 'ProviderIds' in item and item['ProviderIds']['Tmdb'] != tmdbid:
            continue
        if tvdbid and 'ProviderIds' in item and item['ProviderIds']['Tvdb'] != tvdbid:
            continue
        return item

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jellyfin backup/restore")
    parser.add_argument("--username", help="Jellyfin user to back up")
    parser.add_argument("--backup", action="store_true", help="Backup Jellyfin library")
    parser.add_argument("--restore", action="store_true", help="Restore Jellyfin library")
    parser.add_argument("--dryrun", action="store_true", help="Don't actually restore anything")
    args = parser.parse_args()
    if not args.username:
        print("Please specify a Jellyfin user (with --username) to backup")
        sys.exit(1)
    if args.backup:
        backup(args.username)
    if args.restore:
        restore(dryrun=args.dryrun)
    if not args.backup and not args.restore:
        parser.print_help()