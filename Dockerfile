FROM python:3.11

WORKDIR /pear

# Install pyodbc dependencies
RUN curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
RUN curl https://packages.microsoft.com/config/debian/9/prod.list > /etc/apt/sources.list.d/mssql-release.list
RUN apt-get update
RUN ACCEPT_EULA=Y apt-get -y install msodbcsql17
RUN apt-get -y install unixodbc-dev

COPY ./requirements.txt requirements.txt
COPY ./config.py config.py
COPY ./pear_schedule pear_schedule
COPY ./utils.py utils.py
COPY ./app.py app.py

RUN pip install -r requirements.txt

EXPOSE 8080

CMD python app.py start_server -c config.py -p 8080