#!/usr/bin/env python3
"""Toon alle velden van een L-Connect 3 .template: type, positie, databron, lettertype en kleur.
Gebruik: python inspect_template.py pad/naar/bestand.template"""
import sys; import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nrbf import *
d=open(sys.argv[1],'rb').read()
p=Parser(d); recs=p.parse()
root=[r for r in recs if r.kind=='class'][0]
def R(v):
    v=resolve(p,v)
    return None if (v is not None and not isinstance(v,tuple) and v.kind in ('null','nullmulti')) else v
def F(n,k):
    for kk,v in n.fields.items():
        name=kk.split('+')[-1].replace('>k__BackingField','').lstrip('<')
        if name==k: return R(v)
    return None
def val(x):
    if x is None: return None
    if isinstance(x,tuple): return x[2]
    if x.kind=='string': return x.value
    return x
gl=F(root,'GraphList'); lst=F(gl,'Collection`1+items') or R(gl.fields['Collection`1+items'])
arr=R(lst.fields['_items']); size=val(lst.fields['_size'])
for it in arr.items[:size]:
    it=R(it); t=val(F(it,'TypeName'))
    md=F(it,'m_data'); fc=F(it,'fontConfig')
    s=f"{it.cls.split('.')[-1]:14} {t:9} pos=({val(F(it,'posX'))},{val(F(it,'posY'))}) hide={val(F(it,'hide'))}"
    if md: s+=f" data={val(F(md,'DataName'))!r} content={val(F(md,'content'))!r} unit={val(F(md,'ShowUnit'))}"
    if fc:
        c=F(fc,'color'); s+=f" font={val(F(fc,'name'))} {val(F(fc,'size'))} color={val(F(c,'value')):#x}/st{val(F(c,'state'))}"
    if it.cls.endswith('StatuBar'):
        for k in ['FrontColor','BackColor','GradientColor']:
            c=F(it,k); s+=f" {k}={val(F(c,'value')):#x}/kc{val(F(c,'knownColor'))}"
        s+=f" w={val(F(it,'width'))} h={val(F(it,'height'))} fillBack={val(F(it,'fillBack'))} trBack={val(F(it,'trBack'))}"
    print(s)
print('trailing',len(d)-p.p, d[p.p:p.p+80])

print('--- text details')
for it in arr.items[:size]:
    it=R(it)
    if val(F(it,'TypeName')) in ('Text','Data'):
        md=F(it,'m_data'); fc=F(it,'fontConfig'); al=F(fc,'alignment')
        print(val(F(it,'TypeName')), (val(F(it,'posX')),val(F(it,'posY'))), repr(val(F(md,'DataName'))), repr(val(F(md,'DisplayName'))), repr(val(F(md,'ValueWithUnit'))), repr(val(F(md,'_Value'))), 'unit',val(F(md,'ShowUnit')), 'font',val(F(fc,'name')),val(F(fc,'size')),'bold',val(F(fc,'isBold')),'align',val(F(al,'index')),'col',hex(val(F(F(fc,'color'),'value'))),'kc',val(F(F(fc,'color'),'knownColor')), 'grad',val(F(it,'useGradient')))
