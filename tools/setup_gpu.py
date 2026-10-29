"""Fetch pinned official LWJGL jars and Windows x64 natives from Maven Central."""
from pathlib import Path
import hashlib,json,urllib.request
ROOT=Path(__file__).resolve().parents[1]
VERSION='3.3.6'

def install():
    folder=ROOT/'tools/gpu';folder.mkdir(parents=True,exist_ok=True)
    records=[]
    for module in ['lwjgl','lwjgl-glfw','lwjgl-opengl']:
        for suffix in ['', '-natives-windows']:
            name=f'{module}-{VERSION}{suffix}.jar'
            url=f'https://repo.maven.apache.org/maven2/org/lwjgl/{module}/{VERSION}/{name}'
            target=folder/name
            if not target.exists():
                print('Downloading',name,flush=True)
                request=urllib.request.Request(url,headers={'User-Agent':'JAR-Revival/0.2'})
                with urllib.request.urlopen(request,timeout=60) as response:target.write_bytes(response.read())
            records.append({'file':name,'url':url,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    for name,url in [
        ('LWJGL-LICENSE.md',f'https://raw.githubusercontent.com/LWJGL/lwjgl3/{VERSION}/LICENSE.md'),
        ('GLFW-LICENSE.md','https://raw.githubusercontent.com/glfw/glfw/3.4/LICENSE.md'),
    ]:
        target=folder/name
        if not target.exists():
            request=urllib.request.Request(url,headers={'User-Agent':'JAR-Revival/0.2'})
            with urllib.request.urlopen(request,timeout=60) as response:target.write_bytes(response.read())
        records.append({'file':name,'url':url,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    (folder/'dependencies.json').write_text(json.dumps(records,indent=2))
    print('GPU renderer dependencies ready.')

if __name__=='__main__':install()
