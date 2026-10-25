#!/usr/bin/env python3
"""Reference projection plus real v1 parser/semantic checks; requires dev jsonschema."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import copy,json,re,yaml
from jsonschema import Draft202012Validator
from core.manifest import load_manifest,Manifest,ManifestError
from core.manifest.helpers import _load_strict_yaml
p=Path('docs/proposals/capability-parity')
schema=json.loads((p/'recipe-extension.schema.json').read_text());Draft202012Validator.check_schema(schema);v=Draft202012Validator(schema)
keys=['schemaVersion','id','execution','permissions'];loaded={}
for file in (p/'examples').glob('*.yaml'):
 data=yaml.safe_load(file.read_text());assert data==_load_strict_yaml(file.read_text()),file
 loaded[file.name]=data
 if data['schemaVersion']=='cage.app/v1':
  v.validate({k:data[k] for k in keys})
  if 'name' in data:Manifest.from_dict(data)
base=loaded['myharmony.cage.yaml'];projection={k:base[k] for k in keys}
old={k:val for k,val in base.items() if k not in ['id','execution','permissions']};old['schemaVersion']='cage.app/v0'
assert Manifest.from_dict(old).to_dict()==load_manifest(Path('recipes/myharmony.cage.yaml')).to_dict()
assert Manifest.from_dict(base).schema_version=='cage.app/v1'
assert load_manifest(Path('recipes/myharmony.cage.yaml')).schema_version=='cage.app/v0'
valid=[]
def candidate(request):
 d=copy.deepcopy(projection);d['permissions']['requests']=[{'id':'probe','reason':'Exercise the proposed structural contract.',**request}];return d
for request in [
 {'kind':'filesystem','location':{'base':'absolute','path':'/mnt/files'},'access':'read-only'},
 {'kind':'network'}, {'kind':'display','backend':'wayland'},
 {'kind':'device-class','class':'all','hotplug':'required'},
 {'kind':'usb','access':'portal','interfaces':['usb'],'allow':[{'vendor':'046d','product':'c129'}]},
 {'kind':'audio','access':'playback'}, {'kind':'dbus','bus':'session','talk':['org.example.Service']},
 {'kind':'host-service','service':'printing'}, {'kind':'portal','interface':'file-chooser'}]:valid.append(candidate(request))
f=copy.deepcopy(projection);f['execution']['fallbacks']=[{'target':'flatpak','request':'harmony-usb','grant':{'kind':'device-class','class':'all'}}];valid.append(f)
valid += [candidate({'kind':'portal','interface':'file-chooser','required':True}),candidate({'kind':'device-class','class':'all'}),candidate({'kind':'usb','access':'direct','interfaces':['usb','hidraw'],'allow':[{'vendor':'046d'}],'required':True,'presence':'required','hotplug':'required'})]
for case in valid:
 v.validate(case)
 Manifest.from_dict({**base,**case})
variants=schema['properties']['permissions']['properties']['requests']['items']['oneOf']
by_kind={x['properties']['kind']['const']:x for x in variants}
assert by_kind['device-class']['properties']['hotplug']['default']=='startup-only'
assert by_kind['usb']['properties']['hotplug']['default']=='required'
assert 'missing' not in by_kind['filesystem']['properties']
assert 'lifetime' not in by_kind['portal']['properties']
assert 'mode' not in by_kind['network']['properties']
assert 'isolation' not in schema['properties']['execution']['properties']
negative=[]
def badpath(path,value):
 d=copy.deepcopy(projection);node=d
 for k in path[:-1]:node=node[k]
 node[path[-1]]=value;negative.append(d)
for path,value in [
 (['schemaVersion'],'cage.app/v0'),(['unexpected'],True),(['execution','targets'],[]),(['execution','targets'],['oci','oci']),(['execution','isolation'],'auto'),(['execution','environment'],'desktop'),(['id'],'../bad'),(['permissions','extra'],True),
 (['permissions','requests',0,'kind'],'shell'),(['permissions','requests',0,'required'],'yes'),(['permissions','requests',0,'reason'],'line\nbreak'),(['permissions','requests',0,'id'],'Bad ID'),(['permissions','requests',0,'args'],['--privileged']),
 (['permissions','requests',2,'access'],'rw'),(['permissions','requests',2,'access'],'read-only'),(['permissions','requests',2,'wineDrive'],'HH'),(['permissions','requests',2,'location','base'],'env'),(['permissions','requests',2,'location'],{'base':'absolute'}),(['permissions','requests',2,'location'],{'base':'absolute','path':'relative'}),
 (['permissions','requests',3,'allow'],[]),(['permissions','requests',3,'allow'],[{'vendor':'046D'}]),(['permissions','requests',3,'allow'],[{'product':'c129'}]),(['permissions','requests',3,'allow'],[{'vendor':'046d','product':'c129','productRange':{'first':'c110','last':'c14f'}}]),(['permissions','requests',3,'allow'],[{'subclass':'01'}]),(['permissions','requests',3,'allow'],[{'serial':'secret'}]),(['permissions','requests',3,'interfaces'],[]),(['permissions','requests',3,'access'],'portal'),(['permissions','requests',3,'presence'],'present-if-possible'),(['permissions','requests',3,'hotplug'],'best-effort'),
 (['permissions','requests',0,'reason'],'trailing\n'),(['permissions','requests',0,'id'],'trailing\n'),(['id'],'org.example.Trailing\n'),(['permissions','requests',3,'allow'],[{'vendor':'046d\n'}])]:badpath(path,value)
negative += [candidate({'kind':'dbus','bus':'session','talk':[]}),candidate({'kind':'device-class','class':'privileged'}),candidate({'kind':'portal','interface':'usb','lifetime':'persistent'}),candidate({'kind':'portal','interface':'file-chooser','lifetime':'operation'})]
badfallback=copy.deepcopy(f);badfallback['execution']['fallbacks'][0]['grant']['class']='gpu';negative.append(badfallback)
badpath(['permissions','requests',2,'missing'],'omit')
missing_required=candidate({'kind':'usb','access':'direct','interfaces':['usb'],'allow':[{'vendor':'046d'}],'presence':'required'})
false_required=candidate({'kind':'usb','access':'direct','interfaces':['usb'],'allow':[{'vendor':'046d'}],'presence':'required','required':False})
negative += [missing_required,false_required]
for legacy_mode in ['enabled','host-network','isolated','bridge']:
 negative.append(candidate({'kind':'network','mode':legacy_mode}))
for legacy_isolation in ['required','host-access-accepted']:
 badpath(['execution','isolation'],legacy_isolation)
for n,case in enumerate(negative):
 assert list(v.iter_errors(case)),f'negative {n} unexpectedly valid'
 try:Manifest.from_dict({**base,**case})
 except ManifestError:pass
 else:raise AssertionError(f'production parser accepted invalid case {n}')
links=[]
for doc in [p/'README.md',p/'recipe-schema.md',p/'acceptance-tests.md']:
 for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)',doc.read_text()):
  if '://' in target or target.startswith('#'):continue
  target=target.split('#',1)[0];assert (doc.parent/target).exists(),(doc,target);links.append(target)
assert (Path('docs')/'proposals/capability-parity/README.md').exists()
text=(p/'acceptance-tests.md').read_text();test_ids=re.findall(r'^\| ((?:PL|FS|NET|DEV|USB|UX|SVC|POL|ST|TR|ENV|APP|AUTH)[0-9]{2}) \|',text,re.M)
assert len(test_ids)==len(set(test_ids))
refs=set(re.findall(r'\b(?:PL|FS|NET|DEV|USB|UX|SVC|POL|ST|TR|ENV|APP|AUTH)[0-9]{2}\b',(p/'README.md').read_text()));assert refs<=set(test_ids),refs-set(test_ids)
result={'draftSchemaValid':True,'yamlExamplesParsedByBothLoaders':len(loaded),'validFieldProjectionCases':len(valid)+sum(data['schemaVersion']=='cage.app/v1' for data in loaded.values()),'invalidStructuralCasesRejected':len(negative),'newLocalDocumentationLinksChecked':len(links)+1,'acceptanceSpecifications':len(test_ids),'v0ApplicationPayloadPreserved':True,'productionParserSupportsV1':True,'runtimeParityTestsExecuted':False,'deviceClassHotplugDefault':'startup-only','usbHotplugDefault':'required','removedFieldsRejected':True,'usbPresenceRequiresLaunchPrerequisite':True,'executionIsolationFieldRemoved':True,'networkRequestHasNoMode':True}
print(json.dumps(result,indent=2))
