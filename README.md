# Bottlestar

- A bot
- Written in Python
- Focused on the Battlestar Galactica (BSG) board game and its expansions
- Contains data on cards and board locations
- Interfaces (and makes it possible to play) with the By Your Command (BYC) 
  script designed to play BSG on the BoardGameGeek (BGG) forums
- Features search, game state display, and interactive game setups where the 
  bot hosts the game
- Discord and command-line front-ends

## Requirements

- [Python 3.6+](https://www.python.org/downloads/)
- [Virtualenv](https://virtualenv.pypa.io/en/latest/installation.html)
- [ElasticSearch OSS 7](https://www.elastic.co/downloads/elasticsearch-oss)
- [Chrome](https://support.google.com/chrome/answer/95346) or 
  [Chromium](https://www.chromium.org/getting-involved/download-chromium)
- [Chromedriver](https://sites.google.com/a/chromium.org/chromedriver/downloads)
  corresponding to the Chrome/Chromium version

## Setup

- Install the [requirements](#requirements) (which may be available through 
  package managers for your operating system or Python environment, or through 
  the links).
- Set up a Python environment in this directory: `virtualenv -p python3 env`
- Activate the Python environment: `source env/bin/activate`
- Install the Python packages: `pip install -r requirements.txt`
- Using the developer portal of Discord, create a new, aptly-named
  [Application](https://discordapp.com/developers/applications). To add it to 
  a server of which you are not the owner, it must be public in the Bot 
  settings in the portal. On the OAuth2 settings, select the `bot` scope and 
  select the following permissions to enable all capabilities of the bot: 
  Manage Roles, Manage Channels, Manage Nicknames, View Channels, Send 
  Messages, Manage Messages, Embed Links, Attach Files, Read Message History, 
  Mention Everyone (402910224). Then copy the generated URL to add it to your 
  server or send it to a server owner to let them authorize the bot.
- Create a file `config.yml` and fill it with appropriate values for the
  following settings (most are optional but leaving out hinders functionality):

```yaml
token: # Discord API token from the application in the developer portal
cards_url: # URL to index of various BSG card images
rss_url: # URL to RSS feed on BGG to track for updates
thread_id: # ID of the BGG thread to retrieve game state from
api_url: # URL of the BGG API for image/thread/author lookup
session_id: # Session ID to log in to BGG
image_url: # URL prefix of images on BGG
server_id: # Discord ID of the server on which to send update information
channel_id: # Discord ID of the channel on which to send update information
elasticsearch_host: # Hostname where the ElasticSearch endpoint is hosts
script_url: # URL from which to download the BYC script
```

# Usage

- Start the Discord bot simply with `python bot.py --log INFO`. We recommend to 
  run this in a `screen` or similar disconnected shell/process.
- Most bot commands can be seen by using `.help` or `!help` (either character 
  works as prefix for all commands).
- Most bot commands are available in the command-line interface without any
  prefix by running `python cmd.py <command> --log INFO`, either through the 
  byc command or separately. Additional arguments may be provided, and use 
  `python cmd.py --help` for optional arguments.
