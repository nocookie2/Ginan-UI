import re
from datetime import datetime
import pandas as pd
from collections import defaultdict
from pathlib import Path
from dotenv import load_dotenv
import numpy as np


from app.utils.download_products import create_cddis_file
from app.utils.gn_functions import GPSDate





class cddis_handler ():
    def __init__(self, 
                 cddis_str_array:list[str] = None, 
                 cddis_file_path:str = None, 
                 date_time_end_str:str = None
                 ):    
        """
        CDDIS object constructor. Requires CDDIS input and date_time input inorder to access getters 

        :param cddis_str_array:   CDDIS array of products (can be subsituted with cddis_file_path)  
        :param cddis_file_path:   Path to the CDDIS.list file (can be subsituted with cddis_str_array)
        :param date_time_end_str: YYYY-MM-DDTHH:MM Path to the CDDIS.list (optional on init required for query)
        :returns: cddis handeler object 
        """
              
        self.df = None                                     # pd.dataframe of cddis input
        self.valid_products = None                         # pd.dataframe holding valids products
        self.time_end = None                               # user end time bound
        
        if(cddis_str_array != None and cddis_file_path != None):
            raise ValueError("provided only one cddis input")

        if(cddis_str_array != None):
            self.__df_parse_cddis_str_array(cddis_str_array)

        if(cddis_file_path != None):
            self.__parse_product_list_file(cddis_file_path) 

        # optional if class is instantiated and values are not known
        # Note can shift over to YYYY-dddHHmm format if needed through datetime.strptime(date_time,"%Y%j%H%M") 
        if(date_time_end_str != None):
           self.time_end = self.__str_to_datetime(date_time_end_str)

        if(self.df is None and self.time_end is not None):
            self.__download_cddis(self.time_end)
        
        self.__set_valid_products_df()


    def __download_cddis(self, date_time:datetime):
        gps = GPSDate(np.datetime64(date_time))
                  
        try:
            load_dotenv(Path(__file__).parent / "cddis.env")
            create_cddis_file(Path(__file__).parent,gps)
            print(Path(__file__).parent /"CDDIS.list")
            self.__parse_product_list_file(Path(__file__).parent /"CDDIS.list")    
        except: 
            #wasn't able to get the file  
            # Due to timeout                     
            pass

    def __str_to_datetime(self, date_time_str):
        """
        PRIVATE METHOD
        
        :param date_time_str: YYYY-MM-DDTHH:MM
        :returns datetime: datetime.strptime()
        """
        # Note can shift over to YYYY-dddHHmm format if needed through datetime.strptime(date_time,"%Y%j%H%M") 
        try: 
            return datetime.strptime(date_time_str, "%Y-%m-%dT%H:%M")
        except ValueError:             
            raise ValueError("Invalid datetime format. Use YYYY-MM-DDTHH:MM (e.g. 2025-04-14T01:30)")

    def __df_parse_cddis_str_array(self, cddis_str_array:list[str]):
        """
        PRIVATE METHOD


        Generates an pd data frame. 
        
        :param cddis_str_array: input array of line str containg following 
        pattern COD0MGXFIN_20250960000_01D_01D_OSB 
        :returns: None (updates the objects data frame) 
        """  
        # INPUT 
        # COD0MGXFIN_20250960000_01D_01D_OSB.BIA.gz 2025:04:17 10:38:56    63.19KB
        # Most important will be 
        # COD0MGXFIN_20250960000
        # the trailing will be mostly ignored.
        # re.compile(r'^([A-Z0-9]{3})[0-9]([A-Z]{3})([A-Z]{3})_(\d{11})')
        # regex to extract from list 
        # analysis_center    3  char
        # 0                  1  padding   
        # project_type       3  char
        # solution_type      3  char
        # date yyyydddhhmm   11 char 
        
        pattern = re.compile(r'^([A-Z0-9]{3})[0-9]([A-Z]{3})([A-Z]{3})_(\d{11})')
        
        parsed_data = []

        for line in cddis_str_array:

            parts = line.strip().split()        
            if not parts:
                # malformed input
                continue 
            filename = parts[0]

            match = pattern.match(filename)
            if match:
                    analysis_center, project_type, solution_type, end_validity_str = match.groups()
                    try:
                        end_datetime = datetime.strptime(end_validity_str, "%Y%j%H%M") #yyyydddhhmm
                        
                        parsed_data.append({
                            "analysis_center": analysis_center,
                            "project_type": project_type,
                            "solution_type": solution_type,
                            "end_validity": end_datetime,
                            "filename": filename
                        })
                    except ValueError:                        
                        continue
        self.df = pd.DataFrame(parsed_data)

    def __parse_product_list_file(self, file_path:str):
        """
        PRIVATE METHOD

        Generates an pd data frame. 
        
        :param file_path: Path to the CDDIS.list
        :returns: None (updates the objects cddis dataframe)
        """  
        try: 
            with open(file_path, 'r') as file:
                lines = file.readlines()
        except (FileNotFoundError, IOError):
            # ERROR HANDLING 
            #print("Wrong file or file path")
            raise Exception("cddis_handler __parse_product_list_file: Wrong file or file path")

        self.__df_parse_cddis_str_array(lines)
    
    def __set_valid_products_df(self):
        """
        PRIVATE METHOD

        Sets the valid products data frame if valid date time and cddis data frame is available in object. 
        Is called after some value has been set in object. Will then update valid_products data frame 
        """
        if(self.time_end != None and 
           not isinstance(self.df, type(None))
           ):
            self.valid_products = self.get_valid_products_by_datetime(date_time=self.time_end)
                    
    def set_cddis_str_array(self,cddis_str_array:list[str]):
        """
        method will set cddis internals. based on provided CDDIS list of strings 
        If the object has been given an date time then it will also populate 
        the objects valid products data frame.  

        :param cddis_str_array: e.g ["COD0MGXFIN_20250960000_01D_01D_OSB","COD0MGXFIN_20250960000_01D_01D_OSB"] 

        :returns: None (updates object internals)
        """
        self.__df_parse_cddis_str_array(cddis_str_array)
        self.__set_valid_products_df()

    def set_cddis_file_path(self,cddis_file_path:str):
        """
        method will set cddis internals. based on provided CDDIS list file 
        If the object has been given an date time then it will also populate 
        the objects valid products data frame.  

        :param cddis_file_path: path to cddis file

        :returns: None (updates object internals)
        """
        self.__parse_product_list_file(cddis_file_path)
        self.__set_valid_products_df()

    def set_date_time_end(self,date_time_end_str:str):
        """
        method will set cddis internals. based on provided date time 
        If the object has been given an date time then it will also populate 
        the objects valid products data frame.  

        :param date_time_end_str: YYYY-MM-DDTHH:MM (e.g. 2025-04-14T01:30) 

        :returns: None (updates object internals)
        """
        
        # should really create a dedicated helper function for this 

        self.time_end = self.__str_to_datetime(date_time_end_str)
        self.__download_cddis(self.time_end)
        self.__set_valid_products_df()
        



    def get_valid_products_by_datetime(self, date_time_str:str = None, date_time: datetime = None):
        """
        gets a dataframe of valid products by datetime based on input date time and object CDDIS list

        :param date_time_str: YYYY-MM-DDTHH:MM (e.g. 2025-04-14T01:30)
        :param date_time: datetime.strptime(date_time_str, "%Y-%m-%dT%H:%M")
        :returns valid_products: pd.df of valid products in ({"analysis_center": [], "analysis_center": [(project_type,solution_type)]}) if no valids then return empty df
        """
        if(date_time == None and date_time_str == None):
            raise ValueError("cddis_handler get_valid_products_by_datetime: Requires time input")
        elif(date_time != None and date_time_str != None):
            raise ValueError("cddis_handler get_valid_products_by_datetime: too many time input")    
        elif date_time == None:
            date_time = self.__str_to_datetime(date_time_str)

        # Client Provided Code
        # no lower bound <(*)> potent handleing on cddis.list side
        # This will check if there are any products that
        # Valid for the given query time.  
        # Follows the same logic from client provided code
        # Where it will check if there is a product that exceeds the query time
        valid_products = self.df[self.df["end_validity"] >= date_time]
        
        result = defaultdict(set)
        for _, row in valid_products.iterrows():
            result[row["analysis_center"]].add((row["project_type"], row["solution_type"]))
        return pd.DataFrame([
            {"analysis_center": k, "available_types": sorted(list(v))}
            for k, v in result.items()
        ])
    
    def get_list_of_valid_analysis_centers(self) -> list[str]:
        """
        outputs a list str of valid analysis centers

        :param: None
        :return list[str]: list string of valid analysis centers
        """
        return self.valid_products["analysis_center"].unique()

    def get_df_of_valid_types_tuples(self,analysis_center:str):
        """
        outputs a pandas data frame of valid tuple pairings of project-type solution-type 
        for given analysis_center  

        :param analysis_center: target analysis center  
        :return: pd.df in form of ({project-type: str,solution-type str) 
        """
        #long boi
        tuple_array = self.valid_products.loc[self.valid_products["analysis_center"]==analysis_center].iloc[0]["available_types"]      
        df = pd.DataFrame(tuple_array, columns=['project-type','solution-type'])
        return df
    
    def get_list_of_valid_project_types(self,analysis_center:str) -> list[str]:
        """
        outputs a list string of valid_project_types

        :param analysis_center: target analysis center  
        :return: list string of valid_project_types
        """
        df = self.get_df_of_valid_types_tuples(analysis_center)
        return df['project-type'].unique().tolist() 
        
    def get_list_of_valid_solution_types(self,analysis_center:str)-> list[str]:
        """
        outputs a list string of valid_solution_types

        :param analysis_center: target analysis center  
        :return: list string of valid_solution_types
        """
        df = self.get_df_of_valid_types_tuples(analysis_center)
        return df['solution-type'].unique().tolist() 
    
    def is_valid_project_solution_tuple(self, analysis_center:str, project_type:str, solution_type:str):
        """
        Verification of sanatised user input of analysis_center project_type solution_type
 
        :param analysis_center: user input analysis_center
        :param project_type:    user input project_type
        :param solution_type:   user input solution_type
        
        :return: bool valid if user input is valid
        """
        df_valid_tuples = self.get_df_of_valid_types_tuples(analysis_center)
            
        is_empty = df_valid_tuples[(df_valid_tuples["project-type"] == project_type) & 
                        (df_valid_tuples['solution-type'] == solution_type)].empty
        
        #if empty then invalid  if not then valid
        return not is_empty

    def get_optimal_project_solution_tuple(self,analysis_center:str,satellite_constellations = None) -> tuple[str, str]:
                
        """
        From available valids from selected anaylis_center
        solution_type_priorities FIN -> RAP -> ULT  
        Future proof satellite_constellations will help determine the project_type 

        :param analysis_center: target analysis center
        :param satellite_constellations: NOT IMPLEMENTED
        :return: on success (project_type,solution_type) else (None,None)
        """
        # place holder for future proofing for yaml read in 
        # logic for determining project_type priorites
        # probably store some sort of tuple set in resourses folder
        project_type_priorities = None
        if(satellite_constellations == None):
            project_type_priorities = ["MGX"] # "OPS","DEM"
        else:
            raise NotImplementedError("satellite_constellations used in  project_type_priorities not implemented yet")
        
        solution_type_priorities = ["FIN","RAP","ULT"]
        
    
        priority_mapping = None

        df_valid_tuples = self.get_df_of_valid_types_tuples(analysis_center)

        for project_type_priority in project_type_priorities:
            valid_solution_types = df_valid_tuples[(df_valid_tuples["project-type"] == project_type_priority)]['solution-type'].to_list()
            for solution_type_priority in solution_type_priorities:
                if(solution_type_priority in valid_solution_types):
                    return project_type_priority,solution_type_priority
                           
        return None,None


if __name__ == "__main__":
    my_cddis = cddis_handler(date_time_end_str="2024-04-14T01:30")
    #my_cddis = cddis_handler(cddis_file_path="app/resources/cddis_temp/CDDIS.list",date_time_end_str="2024-04-14T01:30")
    print(my_cddis.df)
    print(my_cddis.valid_products)
    print(my_cddis.get_list_of_valid_analysis_centers())
    print(my_cddis.get_df_of_valid_types_tuples("COD"))
    print(my_cddis.get_list_of_valid_project_types("COD"))
    print(my_cddis.get_list_of_valid_solution_types("COD"))
    print(my_cddis.is_valid_project_solution_tuple("COD","MGX","FIN"))
    print(my_cddis.get_optimal_project_solution_tuple("COD"))
    print(my_cddis.get_optimal_project_solution_tuple("EMR"))
    my_cddis.set_date_time_end("2025-07-14T01:30")
    print(my_cddis.time_end)
    print(my_cddis.df)
    print(my_cddis.valid_products)




