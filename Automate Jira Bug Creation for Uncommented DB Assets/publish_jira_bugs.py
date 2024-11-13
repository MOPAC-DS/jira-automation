## MOPAC DB COMMENT TIDY UP

## Daniel Hammocks - 2024-11-12
## GH: dhammo2

## This code connects to the MOPAC DB and identifies any tables
## and columns without a comment. The code then checks, creates, 
## or reassigns a JIRA issue to notify the respective owner.

###############################################################################
############################### MOPAC DB TIDY UP ##############################
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

#File Path to DB JIRA User Mapping
fileUserMap = 'db_jira_usermap_dh.json'


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


#%% JIRA CONNECTION & SETTINGS


# Database and JIRA connection settings
JIRA_CONFIG = LoadCredentials(fileJiraConfig)

# JIRA Project key where issues will be created
JIRA_PROJECT_KEY = 'EI'

# JIRA Parent key where issues will be created
JIRA_PARENT_KEY = 'EI-920'

# JIRA transition ID for reopening an issue
    # See Bottom of Code for Obtaining These
REOPEN_TRANSITION_ID = '11'  
 

# Initialize JIRA connection
    # Jira Cloud: a username/token tu
jira = JIRA(server =JIRA_CONFIG['server'],
            basic_auth=(JIRA_CONFIG['username'],
                        JIRA_CONFIG['api_key']))


#%% LOAD USER MAPPING

# Dictionary mapping database usernames to JIRA usernames
USER_MAP = LoadCredentials(fileUserMap)


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
        
        
#%% IDENTIFICATION

# Connect to the PostgreSQL database
def fetch_uncommented_objects(query):
    
    cnx = Connect2DB(fileDBCredentials)
    
    with cnx.cursor() as cur:
    
        cur.execute(query)
        uncommented_objects = cur.fetchall()
        cur.close()
        cnx.close()
    
    return uncommented_objects


def filter_uncommented_objects(uncommented_objects):
    
    #Remove postgres tables
    filtered_data = [t for t in uncommented_objects if t[1] not in ('information_schema', 'pg_catalog')]

    #Remove features added by system
    filtered_data = [t for t in filtered_data if t[3] not in ('rdsadmin')]
    
    #Remove personal tables
    filtered_data = [t for t in filtered_data if not t[1].startswith('udb_')]
    
    return filtered_data


#%% JIRA MANIPULATION

def issue_exists(jira, summary):
    issues = jira.search_issues(f'project = "{JIRA_PROJECT_KEY}" AND summary ~ "{summary}"')
    return issues[0] if issues else None

def reopen_issue(jira, issue):
    # Reopen the issue using the specified transition ID
    jira.transition_issue(issue, REOPEN_TRANSITION_ID)
    print(f"Issue {issue.key} transitioned back to open status.")

def create_jira_issue(jira, summary, description, db_owner):
    # Look up the JIRA username from the USER_MAP
    jira_assignee = USER_MAP.get(db_owner)
    
    if not jira_assignee:
        print(f"No JIRA username found for database user '{db_owner}'. Skipping issue creation.")
        return
    
    issue_dict = {
        'project': {'key': JIRA_PROJECT_KEY},
        'parent' : {'key': JIRA_PARENT_KEY},
        'summary': summary,
        'description': description,
        'issuetype': {'name': 'Sub-task'}
    }
    jira.create_issue(fields=issue_dict)

def assign_jira_user(jira, summary, db_owner):
    
    jira_assignee = USER_MAP.get(db_owner)
    
    if not jira_assignee:
        print(f"No JIRA username found for database user '{db_owner}'. Skipping issue creation.")
        return
    
    #Risky Operation
    max_retries = 3  # Number of times to retry
    wait_time = 10  # Time to wait between retries (in seconds)
    
    for attempt in range(max_retries):
        
        try:
            # Try performing the risky operation
            issue = issue_exists(jira, summary)
            jira.assign_issue(issue, jira_assignee)
            
            # Exit loop if operation succeeds
            break
        
        except Exception as e:
            
            if attempt < max_retries - 1:
                
                # Wait before the next attempt
                time.sleep(wait_time)
                
            else:
                print(f"Could not assign JIRA user '{db_owner}' to {issue}.")
    

        

#%% MAIN

# Main function to identify uncommented objects and create or reopen JIRA issues
def main():
    
    uncommented_objects = fetch_uncommented_objects(query)
    uncommented_objects = filter_uncommented_objects(uncommented_objects)
    

    for obj in uncommented_objects:
        schema_name, table_name, owner, obj_type = obj[1], obj[2], obj[3], obj[4]
        
        # Construct the summary based on whether the object is a table or column
        if obj_type == "TABLE":
            summary = f"Missing COMMENT on {schema_name}.{table_name}"
            
        else:  # For columns
            column_name = obj_type.split(": ")[1]
            summary = f"Missing COMMENT on {schema_name}.{table_name}.{column_name}"
        
        description = (f"The {obj_type.lower()} `{schema_name}.{table_name}` is missing a COMMENT. "
                       f"Please add a COMMENT to meet documentation standards.")
        

        # Check if a JIRA issue for this object already exists using the standardized summary
        issue = issue_exists(jira, summary)
        
        
        if issue:
            # Check if the issue is marked as "Done" or "Resolved"
            if issue.fields.status.name.lower() in ["done", "resolved", "ended"]:
                print(f"Reopening JIRA issue {issue.key} for {summary}")
                reopen_issue(jira, issue)
                
            else:
                print(f"JIRA issue {issue.key} already exists and is open for {summary}")
                
        else:
            print(f"Creating JIRA issue for {summary}")
            create_jira_issue(jira, summary, description, owner)
            assign_jira_user(jira, summary, owner)

            

if __name__ == "__main__":
    main()




#%% CODE USED TO IDENTIFY ISSUE TRANSITION

# import requests
# from requests.auth import HTTPBasicAuth

# # JIRA credentials
# jira_email        = JIRA_CONFIG['username']  # Your JIRA email
# jira_api_token    = JIRA_CONFIG['password']  # Your JIRA API token
# jira_instance_url = JIRA_CONFIG['server']    # Your JIRA instance URL

# # Issue key for which you want to get transitions
# issue_key = "EI-978"

# # Define the endpoint for getting transitions
# url = f"{jira_instance_url}/rest/api/2/issue/{issue_key}/transitions"

# # Make the GET request
# response = requests.get(
#     url,
#     auth=HTTPBasicAuth(jira_email, jira_api_token),
#     headers={"Accept": "application/json"}
# )

# if response.status_code == 200:
#     transitions = response.json().get("transitions", [])
#     print("Available transitions:")
#     for transition in transitions:
#         print(f"ID: {transition['id']}, Name: {transition['name']}, To Status: {transition['to']['name']}")
# else:
#     print(f"Failed to fetch transitions. Status code: {response.status_code}, Response: {response.text}")