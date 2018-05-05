# Author: Samuel Guebo, Derick Alangi
# Description: Entry point of the application
# License: MIT

import requests
import re

class Test:   
    def dynamicMessage(self):    
        page = "User:SSethi (WMF)/Sandbox/Gerrit newcomer bot text"
        # build the API requst url
        url = "https://www.mediawiki.org/w/index.php?title=" + page + "&action=raw";
        r = requests.get(url)
        content = r.text
        
        # remove tags
        content = re.compile(r'<.*?>').sub('', content)

        return content
    
    def echo (self):
        return self.dynamicMessage()

test = Test()
print(test.echo())
