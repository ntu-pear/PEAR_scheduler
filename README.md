# Installation

## For any unix OS use the makefile

`make build`

## Windows 
On PowerShell
1. `.\env\Scripts\Activate.ps1 `
2. `python app.py start_server -c configprod.py -p 8080`

If env files are causing error, or it is your first time running
1. delete the env folder
2. In cmd run the following:  
`py -3.11 -m venv env && env\Scripts\activate && pip install -r requirements.txt`



# Running

## start rest server
`python app.py start_server -c configprod.py`

## run schedule updates from cli
`python app.py refresh_schedules -c configprod.py`
