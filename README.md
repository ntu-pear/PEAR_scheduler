# Installation

## For any unix or other non-joke OS use the makefile

`make build`

## Windows

redo this each time u want to rebuild

1. delete the env folder
2. In cmd run the following:  
`py -3.11 -m venv env && env\Scripts\activate && pip install -r requirements.txt`

# Running

## start rest server
`python app.py start_server -c config.py`

## run schedule updates from cli
`python app.py refresh_schedules -c config.py`