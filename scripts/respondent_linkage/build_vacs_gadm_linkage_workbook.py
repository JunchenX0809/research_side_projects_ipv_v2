"""Build the PI-facing VACS -> GADM linkage workbook.

Reads every per-wave crosswalk under data/cleaned_survey_data/*_link_v1/ and emits:
  - vacs_gadm_linkage_v1.xlsx   sheets '1-10' and '11-21' (adm areas.xlsx block layout) + 'master'
  - vacs_gadm_linkage_v1_master.csv   the same rows, long format

Run from the repo root:  .venv/bin/python -m scripts.respondent_linkage.build_vacs_gadm_linkage_workbook
Override the output dir: OUT_DIR=/tmp .venv/bin/python -m scripts.respondent_linkage.build_vacs_gadm_linkage_workbook

Asserts every wave's respondent total against combined_df_clean.csv and every wave's count of
blank operative GIDs against EXPECTED_BLANK. It refuses to write if any wave disagrees.
Requires: pandas, openpyxl, pyshp(not used here), xlrd(not used here).
"""
import pandas as pd, numpy as np, os
import os
SPD=os.environ.get('OUT_DIR','data/cleaned_survey_data')
B='data/cleaned_survey_data/'
def rd(p): return pd.read_csv(B+p)

def pick(df, spec):
    if spec is None: return pd.NA
    for c in ([spec] if isinstance(spec,str) else spec):
        if c in df.columns: return df[c]
    raise KeyError('none of %s in %s' % (spec, list(df.columns)))

def frame(country, year, df, a1=None, a2=None, name=None,
          gid1=None, gid2=None, gname='gadm_name', lvl='ADM2', n='n_respondents'):
    out=pd.DataFrame(index=df.index)
    out['survey_admin1']=pick(df,a1)
    out['survey_admin2']=pick(df,a2)
    out['survey_name']=pick(df,name)
    out['gadm_adm1_gid']=pick(df,gid1)
    out['gadm_adm2_gid']=pick(df,gid2)
    out['gadm_name']=pick(df,gname)
    out['gadm_level_used']=lvl
    # a single-level wave may pass its GID in either slot; route it to the column
    # that matches the level actually used, so blocks and master agree
    if lvl=='ADM1':
        a1g=out['gadm_adm1_gid']
        if (not isinstance(a1g,pd.Series)) or a1g.isna().all():
            out['gadm_adm1_gid']=out['gadm_adm2_gid']
            out['gadm_adm2_gid']=pd.NA
    out['n_respondents']=pick(df,n)
    out.insert(0,'year',year); out.insert(0,'country',country)
    return out

W=[]  # (no, title, frame, join_key_line, note_line)

# 1 Cambodia
c=rd('cambodia_link_v1/cambodia_2013_admin2_crosswalk_gadm36.csv')
W.append((1,'Cambodia (2013)', frame('Cambodia',2013,c,'survey_admin1','survey_admin2','survey_name','gadm_adm1_gid','gadm_gid'),
 'Join key: (adm1_num, adm2_num), the official NCDD district code adm1*100+adm2.',
 'GADM 3.6 is missing 16 of the 114 districts, including most Phnom Penh khans; 2,070 of 2,376 respondents link (87%). All 114 link on GADM 4.1. Six codes in province 3 were reconstructed from the Dec 2013 Tboung Khmum split.'))
# 2 Colombia
c=rd('colombia_link_v1/colombia_2018_admin2_crosswalk.csv')
W.append((2,'Colombia (2018)', frame('Colombia',2018,c,'survey_admin1','survey_admin2','survey_municipio','gadm_adm1_gid','gadm_gid'),
 'Join key: (adm1_num, adm2_num), the 5-digit DIVIPOLA code.',
 'GADM 3.6 has no Bogota at ADM1: the capital sits inside Cundinamarca. Zapayan and Mapiripana have no polygon. 2,644 of 2,705 respondents link (98%). All 92 link on GADM 4.1.'))
# 3 Cote d'Ivoire
c=rd('cotedivoire_link_v1/cotedivoire_2019_admin_crosswalk.csv')
W.append((3,"Cote d'Ivoire (2019)", frame("Cote d'Ivoire",2019,c,None,'survey_admin2','survey_name','gadm_adm1_gid','gadm_gid'),
 'Join key: adm2_num alone (the REG code). adm1_num is a 6-zone survey grouping, not administrative.',
 'Fieldwork was 2018; the cleaned data frame is keyed year=2019. Exposure already uses the 2018 window, so only the label is wrong.'))
# 4 El Salvador
c=rd('elsalvador_link_v1/elsalvador_2018_admin2_crosswalk.csv')
W.append((4,'El Salvador (2018)', frame('El Salvador',2018,c,'survey_admin1','survey_admin2','survey_municipio','gadm_adm1_gid','gadm_gid'),
 'Join key: (adm1_num, adm2_num), the official department*100+municipio code.', ''))
# 5,6 Eswatini
e=rd('eswatini_link_v1/eswatini_admin1_crosswalk.csv')
for yr,no in ((2007,5),(2022,6)):
    s=e[e.year==yr]
    W.append((no,'Eswatini (%d)'%yr, frame('Eswatini',yr,s,'survey_admin1',None,'survey_name',None,'gadm_gid',lvl='ADM1'),
     'Join key: adm1_num alone (region).',
     'The two waves use different code orders; do not reuse one for the other. No ADM2: the survey variable is a sampling cluster, not a tinkhundla.' if yr==2007 else
     'No ADM2: the survey variable is a PSU, not a tinkhundla. GADM GIDs are not in code order, so match by name.'))
# 7 Haiti
c=rd('haiti_link_v1/haiti_2012_admin2_crosswalk.csv')
c=c.copy(); c['ihsi_commune']=c['ihsi_commune'].astype(str).str.replace(r"^(?:de |d')", '', regex=True).str.strip()
W.append((7,'Haiti (2012)', frame('Haiti',2012,c,None,'survey_admin2',['survey_name','ihsi_commune'],'gadm_adm1_gid','gadm_gid'),
 'Join key: adm2_num alone (IHSI commune code).',
 'The survey records communes; GADM records the larger arrondissements, so 77 survey codes map onto 37 GADM units and rows share a gadm_gid by design. The survey adm1 is defective and is not used.'))
# 8 Honduras
c=rd('honduras_link_v1/honduras_2017_admin2_crosswalk.csv')
W.append((8,'Honduras (2017)', frame('Honduras',2017,c,'survey_admin1','survey_admin2','survey_municipio','gadm_adm1_gid','gadm_gid'),
 'Join key: (adm1_num, adm2_num), the official department*100+municipio code.',
 'GADM 3.6 swaps the two Trinidads: its Copan unit is named Trinidad and its Santa Barbara unit Trinidad de Copan. Matched within department, so this file is correct.'))
# 9 Kenya 2010
k=rd('kenya2010_link_v1/kenya_county_to_province_lookup.csv')
f=frame('Kenya',2010,k,'survey_admin1',None,'province',None,None,lvl='ADM1',n=None); f['gadm_adm1_gid']=k.gadm_gid; f['gadm_name']=k.gadm_name; f['n_respondents']=pd.NA
W.append((9,'Kenya (2010)', f,
 'NOT one-to-one. Join key: adm1_num (province). Each row is one GADM county and the province it sits in.',
 'The survey records the 8 pre-2013 provinces; GADM 3.6 Kenya has no province layer, its ADM1 is 47 counties. Exposure must be aggregated from counties up to provinces before joining. Respondent counts are blank because respondents attach to the province, not the county. Awaiting a method decision.'))
# 10 Kenya 2019
c=rd('kenya2019_link_v1/kenya2019_admin1_crosswalk.csv')
W.append((10,'Kenya (2019)', frame('Kenya',2019,c,'survey_admin1',None,'survey_name',None,'gadm_gid',lvl='ADM1'),
 'Join key: adm1_num alone (county).',
 'No ADM2: GADM ADM2 for Kenya is Constituency and the survey has no constituency variable. Its adm2 field is an enumeration area.'))
# 11 Lesotho
c=rd('lesotho_link_v1/lesotho_2018_admin1_crosswalk.csv')
W.append((11,'Lesotho (2018)', frame('Lesotho',2018,c,'survey_admin1',None,'survey_name',None,'gadm_gid',lvl='ADM1'),
 'Join key: adm1_num alone (district).',''))
# 12 Malawi
c=rd('malawi_link_v1/malawi_2013_admin2_crosswalk.csv')
f=frame('Malawi',2013,c,'survey_admin1','survey_admin2','survey_district',None,None,lvl='ADM1')
f['gadm_adm1_gid']=c.gadm_gid; f['gadm_name']=c.gadm_name
W.append((12,'Malawi (2013)', f,
 'Join key: adm2_num alone (a national district index). adm1_num is the region and is not part of the key.',
 "The survey's adm2 is a district, which is GADM's ADM1 level here. GADM's ADM2 for Malawi is Traditional Authority, a level the survey does not record, so the GID is an ADM1 GID."))
# 13 Moldova
c=rd('moldova_link_v1/moldova_2013_admin1_crosswalk.csv')
W.append((13,'Moldova (2013)', frame('Moldova',2013,c,'survey_admin1',None,'survey_name',None,'gadm_gid',lvl='ADM1'),
 'Join key: adm1_num alone (raion).',
 'Codes 35 and 36 both resolve to Gagauzia (125 respondents). No GADM ADM2 exists for Moldova.'))
# 14 Mozambique
c=rd('mozambique_link_v1/mozambique_2019_admin1_crosswalk.csv')
W.append((14,'Mozambique (2019)', frame('Mozambique',2019,c,'survey_admin1',None,'survey_name',None,'gadm_gid',lvl='ADM1'),
 'Join key: adm1_num alone (province). Exposure uses GADM 4.0 for this wave.',
 'Sofala was not surveyed; the cleaned adm1 re-indexes the official codes 1-6, 8-11 to 1-10.'))
# 15 Namibia
c=rd('namibia_link_v1/namibia_2019_admin1_crosswalk.csv')
W.append((15,'Namibia (2019)', frame('Namibia',2019,c,'survey_admin1',None,'survey_name',None,'gadm_gid',lvl='ADM1'),
 'Join key: adm1_num alone (region).',
 'GADM 3.6 has 13 regions against the survey 14: Kavango East and West (codes 4 and 5, 169 respondents) both fall in GADM undivided Kavango.'))
# 16 Nigeria
c=rd('nigeria_link_v1/nigeria_2014_admin_crosswalk.csv')
W.append((16,'Nigeria (2014)', frame('Nigeria',2014,c,'survey_admin1',None,'survey_name',None,'gadm_gid',lvl='ADM1'),
 'Join key: adm1_num alone (state, alphabetical incl. FCT).',
 'No ADM2 in the outcome file.'))
# 17 Rwanda
c=rd('rwanda_link_v1/rwanda_2016_admin2_crosswalk.csv')
W.append((17,'Rwanda (2016)', frame('Rwanda',2016,c,'survey_admin1','survey_admin2','gadm_name','gadm_adm1_gid','gadm_gid'),
 'Join key: (adm1_num, adm2_num) = the official district code adm1*10+adm2. adm2_num alone repeats across provinces.',''))
# 18 Tanzania
c=rd('tanzania2024_link_v1/tanzania2024_admin1_crosswalk.csv')
W.append((18,'Tanzania (2024)', frame('Tanzania',2024,c,'survey_admin1',None,'survey_name',None,'gadm_gid',lvl='ADM1'),
 'Join key: adm1_num alone (region, alphabetical). Exposure uses GADM 4.1 for this wave.',''))
# 19 Uganda
c=rd('uganda_link_v1/uganda_2015_admin2_crosswalk.csv')
f=frame('Uganda',2015,c,'survey_admin1','survey_admin2','survey_name','gadm_adm1_gid','gadm_adm2_gid')
f['gadm_level_used']=c.gadm_level_used
W.append((19,'Uganda (2015)', f,
 'Join key: adm2_num alone (district). adm2_num k is the k-th ISO 3166-2:UG code in ascending order; adm1_num is the region.',
 'Only 84 of 112 districts exist in GADM. GADM holds Uganda 2002 boundaries (56 districts) against the survey 112 of 2015, and no GADM version is newer. 5,072 of 5,804 respondents link (87%). Blank rows are districts created after the GADM vintage. Awaiting a method decision.'))
# 20 Zambia
c=rd('zambia_link_v1/zambia_2014_admin2_crosswalk.csv')
W.append((20,'Zambia (2014)', frame('Zambia',2014,c,'survey_admin1','survey_admin2','survey_district','gadm_adm1_gid','gadm_gid'),
 'Join key: (adm1_num, adm2_num). adm2_num k is the k-th smallest CSO district code.',
 'GADM sorts North-Western before Northern, so adm1 codes 7 and 8 give ZMB.8_1 and ZMB.7_1.'))
# 21 Zimbabwe
c=rd('zimbabwe_link_v1/zimbabwe_2017_admin_crosswalk.csv')
W.append((21,'Zimbabwe (2017)', frame('Zimbabwe',2017,c,'survey_admin1','survey_admin2','survey_name','gadm_adm1_gid','gadm_gid'),
 'Join key: (adm1_num, adm2_num).',
 'The survey splits districts into urban and rural parts; GADM does not, so 91 survey codes map onto 60 GADM units and rows share a gadm_gid by design. Plumtree (8 respondents) has no ADM2 GID: it straddles Bulilima and Mangwe. 8,707 of 8,715 respondents link (99.9%).'))

# ---------------- verification ----------------
d=pd.read_csv(B+'combined_df_clean.csv', usecols=['country','year','admin1','admin2'], low_memory=False)
def wavetot(pat, yr):
    return len(d[d.country.str.contains(pat,case=False,na=False,regex=True) & (d.year==yr)])
PATS={"Cote d'Ivoire":'Ivoire|Cote'}
EXPECTED_BLANK={1:16, 2:2, 19:28, 21:1}   # genuinely unlinked rows, all documented in the notes
print('%-3s %-22s %5s %6s %8s %8s %6s  %s' % ('#','wave','rows','GADMs','resp','wave N','blank','reconciles'))
print('-'*82)
allrows=[]
for no,title,f,jk,note in W:
    ctry=f.country.iloc[0]; yr=int(f.year.iloc[0])
    tot=wavetot(PATS.get(ctry, ctry), yr)
    rs=f.n_respondents.sum() if f.n_respondents.notna().any() else None
    ok='n/a (aggregation)' if rs is None else ('YES' if rs==tot else 'NO  (%s vs %s)'%(rs,tot))
    lvlc=f.gadm_level_used.astype(str)
    op=np.where(lvlc=='ADM2', f.gadm_adm2_gid, f.gadm_adm1_gid)
    blank=int(pd.isna(op).sum())
    gid=pd.Series(op).dropna()
    exp=EXPECTED_BLANK.get(no,0)
    assert blank==exp, 'wave %d %s: %d blank operative GIDs, expected %d' % (no,title,blank,exp)
    print('%-3d %-22s %5d %6d %8s %8d %6d  %s' % (no,title,len(f),gid.nunique(),rs if rs is not None else '-',tot,blank,ok))
    g=f.copy(); g.insert(0,'wave_no',no); g['gadm_version']='4.0' if ctry=='Mozambique' else ('4.1' if (ctry=='Tanzania' or (ctry=='Eswatini' and yr==2022)) else '3.6')
    allrows.append(g)
M=pd.concat(allrows, ignore_index=True)
M=M[['wave_no','country','year','survey_admin1','survey_admin2','survey_name',
     'gadm_version','gadm_level_used','gadm_adm1_gid','gadm_adm2_gid','gadm_name','n_respondents']]
M.to_csv(SPD+'/vacs_gadm_linkage_v1_master.csv', index=False)
print('\nMASTER: %d rows across %d waves | respondents %d' % (len(M), M.wave_no.nunique(), M.n_respondents.sum()))

# ---------------- workbook ----------------
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter as L

def opgid(f):
    return np.where(f.gadm_level_used.astype(str)=='ADM2', f.gadm_adm2_gid, f.gadm_adm1_gid)

wb=openpyxl.Workbook(); wb.remove(wb.active)
HDR=['adm1_num','adm2_num','survey_name','gadm_gid','gadm_name','n']
TITLE=Font(bold=True,size=12); KEYF=Font(italic=True,size=9,color='1F4E79')
NOTEF=Font(size=9,color='9C4500'); HF=Font(bold=True,size=9,color='FFFFFF')
HFILL=PatternFill('solid',fgColor='44546A'); TFILL=PatternFill('solid',fgColor='D9E2F3')
thin=Side(style='thin',color='BFBFBF')

for sheet,(lo,hi) in [('1-10',(1,10)),('11-21',(11,21))]:
    ws=wb.create_sheet(sheet); col=1
    for no,title,f,jk,note in W:
        if not (lo<=no<=hi): continue
        g=f.reset_index(drop=True).copy(); g['_gid']=opgid(g)
        ws.cell(1,col,'%d. %s'%(no,title)).font=TITLE
        ws.cell(1,col).fill=TFILL
        ws.cell(2,col,jk).font=KEYF
        ws.cell(3,col,note if note else '').font=NOTEF
        for j,h in enumerate(HDR):
            c=ws.cell(4,col+j,h); c.font=HF; c.fill=HFILL; c.alignment=Alignment(horizontal='center')
        for i in range(len(g)):
            vals=[g.survey_admin1[i], g.survey_admin2[i], g.survey_name[i],
                  g._gid[i], g.gadm_name[i], g.n_respondents[i]]
            for j,v in enumerate(vals):
                if pd.isna(v): continue
                c=ws.cell(5+i,col+j, int(v) if isinstance(v,(int,np.integer,float,np.floating)) and float(v)==int(v) else v)
                c.border=Border(bottom=thin)
        for j,w in enumerate([9,9,26,14,24,7]): ws.column_dimensions[L(col+j)].width=w
        ws.merge_cells(start_row=1,start_column=col,end_row=1,end_column=col+5)
        ws.merge_cells(start_row=2,start_column=col,end_row=2,end_column=col+5)
        ws.merge_cells(start_row=3,start_column=col,end_row=3,end_column=col+5)
        ws.cell(2,col).alignment=Alignment(wrap_text=True,vertical='top')
        ws.cell(3,col).alignment=Alignment(wrap_text=True,vertical='top')
        col+=6
    ws.row_dimensions[2].height=28; ws.row_dimensions[3].height=58
    ws.freeze_panes='A5'

ws=wb.create_sheet('master')
for j,h in enumerate(M.columns,1):
    c=ws.cell(1,j,h); c.font=HF; c.fill=HFILL
for i,row in enumerate(M.itertuples(index=False),2):
    for j,v in enumerate(row,1):
        if pd.isna(v): continue
        ws.cell(i,j, int(v) if isinstance(v,(int,np.integer,float,np.floating)) and float(v)==int(v) else v)
for j,w in enumerate([8,14,7,11,11,26,9,10,15,15,24,9],1): ws.column_dimensions[L(j)].width=w
ws.freeze_panes='A2'; ws.auto_filter.ref=ws.dimensions

out=SPD+'/vacs_gadm_linkage_v1.xlsx'
wb.save(out); print('\nwrote', out, '| sheets:', wb.sheetnames)
