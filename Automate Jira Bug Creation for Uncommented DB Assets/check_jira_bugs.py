## MOPAC DB COMMENT TIDY UP

## Daniel Hammocks - 2024-11-12
## GH: dhammo2

## This code connects uses the JIRA API to check whether an existing issue has
## already been resolved.

###############################################################################
############################### JIRA BUG CHECKER ##############################
###############################################################################


#%% CHANGELOG

# v1.0.0 - 

#%% NOTES



#%% REQUIRED LIBRARIES

import os
import time
import json
import psycopg2
from jira import JIRA



#%% FILE DIRECTORIES

#os.chdir('/path/subpath')


#%% SCRIPT CONSTANTS

#File Path to Database Credentials File
fileDBCredentials = 'db_credentials_dh.json'

#File Path to Jira Configuration File
fileJiraConfig = 'jira_config_dh.json'


#%% LOAD CREDENTIALS

def LoadCredentials(filepath):
    with open(filepath, 'r') as file:
        return json.load(file)


#%% DATABASE CONNECTION

def Connect2DB(fileDBCredentials):
    try:
        #Load the credentials from the JSON file
        credentials = LoadCredentials(fileDBCredentials)

        #Connect to the PostgreSQL database
        connection = psycopg2.connect(
            host     = credentials['DB_HOST'],
            database = credentials['DB_NAME'],
            user     = credentials['DB_USER'],
            password = credentials['DB_PASS'],
            port     = credentials['DB_PORT']
        )

        #Print PostgreSQL connection properties
        #print("Connection properties:", connection.get_dsn_parameters(), "\n")

        return connection

    except Exception as error:
        print("Error while connecting to PostgreSQL", error)


#%% JIRA CONNECTION

# Database and JIRA connection settings
JIRA_CONFIG = LoadCredentials(fileJiraConfig)

# JIRA Project key where issues will be created
JIRA_PROJECT_KEY = 'EI'

# JIRA Parent to Search for Issues
JIRA_PARENT = 'EI-920' 


# JIRA transition ID for closing an issue
    # See Bottom of Code for Obtaining These
REOPEN_TRANSITION_ID = '41'  
 

# Initialize JIRA connection
    # Jira Cloud: a username/token tu
jira = JIRA(server =JIRA_CONFIG['server'],
            basic_auth=(JIRA_CONFIG['username'],
                        JIRA_CONFIG['api_key']))


#%% DEFINE SQL QUERIES

query = '''
        SELECT 
            c.oid AS table_oid,
            n.nspname AS schema_name,
            c.relname AS table_name,
            pg_catalog.pg_get_userbyid(c.relowner) AS owner,
            'TABLE' AS obj_type
        FROM 
            pg_class c
        JOIN 
            pg_namespace n ON n.oid = c.relnamespace
        WHERE 
            c.relkind = 'r' -- only regular tables
            AND obj_description(c.oid, 'pg_class') IS NULL -- missing table comment
        UNION ALL
        SELECT 
            c.oid AS table_oid,
            n.nspname AS schema_name,
            c.relname AS table_name,
            pg_catalog.pg_get_userbyid(c.relowner) AS owner,
            'COLUMN: ' || a.attname AS obj_type
        FROM 
            pg_class c
        JOIN 
            pg_namespace n ON n.oid = c.relnamespace
        JOIN 
            pg_attribute a ON a.attrelid = c.oid
        WHERE 
            c.relkind = 'r' -- only regular tables
            AND a.attnum > 0 -- ignore system columns
            AND col_description(c.oid, a.attnum) IS NULL -- missing column comment
        ORDER BY 
            schema_name, table_name, obj_type;
        '''
        
        
#%% JIRA FUNCTIONS

def identify_issues(JIRA_PROJECT_KEY, JIRA_PARENT):
    
    # Get issues under parent task
    issues_in_proj = jira.search_issues(f'project = {JIRA_PROJECT_KEY} and parent = {JIRA_PARENT}', maxResults=500)
    
    # Identify the summaries
    results = []
    
    for iss in issues_in_proj:
        
        results.append((iss.key, iss.fields.summary))
        
    return(results)


def get_issue_object(jira, key):
    issues = jira.search_issues(f'project = "{JIRA_PROJECT_KEY}" AND key = "{key}"')
    return issues[0] if issues else None


def mark_issue_complete(jira, issue):

    # Mark the issue using the specified transition ID
    jira.transition_issue(issue, REOPEN_TRANSITION_ID)
    


#%% DATABASE FUNCTIONS

# Connect to the PostgreSQL database
def fetch_uncommented_objects(query):
    
    cnx = Connect2DB(fileDBCredentials)
    
    with cnx.cursor() as cur:
    
        cur.execute(query)
        uncommented_objects = cur.fetchall()
        cur.close()
        cnx.close()
        
    results = []
        
    for obj in uncommented_objects:
        schema_name, table_name, owner, obj_type = obj[1], obj[2], obj[3], obj[4]
        
        # Construct the summary based on whether the object is a table or column
        if obj_type == "TABLE":
            summary = f"Missing COMMENT on {schema_name}.{table_name}"
            
        else:  # For columns
            column_name = obj_type.split(": ")[1]
            summary = f"Missing COMMENT on {schema_name}.{table_name}.{column_name}"
            
        results.append(summary)      
    
    return results


#%% MAIN

def main():
    
    # Fetch Subtasks of Parent Issue
    open_tasks = identify_issues(JIRA_PROJECT_KEY, JIRA_PARENT)
    
    #Remove the "DO NOT REMOVE" Placeholder
    open_tasks = [item for item in open_tasks if item[1] != "DO NOT REMOVE"]
    
    # Get Summary from Missing Comment Objects in Database
    uncommented_objects = fetch_uncommented_objects(query)
    
    # Identify Completed Tasks
    results = [item[0] for item in open_tasks if item[1] not in uncommented_objects]
        
    for result in results:
            
        # Get issue object
        issue = get_issue_object(jira, result)
        
        #Change assignment to done
        mark_issue_complete(jira, issue)
        
        print(f"Closing JIRA issue {issue.key}.")
    
#%%

main()
