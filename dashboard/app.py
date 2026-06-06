import dash
from dash import dcc, html, Input, Output, State, callback
import plotly.graph_objects as go
import pandas as pd
import statistics
import csv
import datetime
import requests

csv.field_size_limit(10**7)

# ── Load data ─────────────────────────────────────────────────────────────────

def load_county_data(path='data/merged_fire_svi.csv'):
    with open(path) as f:
        rows = list(csv.DictReader(f))

    from collections import defaultdict
    county_data = defaultdict(list)
    for r in rows:
        if r.get('county'):
            county_data[r['county']].append(r)

    summaries = {}
    fire_points = {}  # county → list of fire point dicts

    for county, fires in county_data.items():
        evac_fires = [r for r in fires if r.get('alert_lag_mins')]
        lags = [float(r['alert_lag_mins']) / 60 for r in evac_fires]
        svi_row = next((r for r in fires if r.get('rpl_themes')), fires[0])
        big = sorted([r for r in fires if r.get('last_acreage')],
                     key=lambda x: float(x['last_acreage'] or 0), reverse=True)[:3]
        top_fires = []
        for f in big:
            f_lag = float(f['alert_lag_mins']) / 60 if f.get('alert_lag_mins') else None
            try:
                dt = datetime.datetime.strptime(f['date_created'][:7], '%Y-%m')
                date_fmt = dt.strftime('%b %Y')
            except:
                date_fmt = f['date_created'][:7]
            top_fires.append({'name': f['name'], 'date': date_fmt,
                              'acres': float(f['last_acreage']),
                              'lag': round(f_lag, 1) if f_lag else None})

        # Build fire points for scatter overlay
        pts = []
        for r in fires:
            if not (r.get('lat') and r.get('lng')):
                continue
            try:
                lat = float(r['lat'])
                lng = float(r['lng'])
            except:
                continue
            acres = float(r['last_acreage']) if r.get('last_acreage') else None
            lag = float(r['alert_lag_mins']) / 60 if r.get('alert_lag_mins') else None
            has_evac = r.get('had_evac_order') == '1.0'
            try:
                date_str = datetime.datetime.strptime(
                    r['date_created'][:7], '%Y-%m').strftime('%b %Y')
            except:
                date_str = r['date_created'][:7] if r.get('date_created') else '—'
            pts.append({
                'lat': lat, 'lng': lng,
                'name': r.get('name') or 'Unnamed fire',
                'date': date_str,
                'acres': acres,
                'lag': round(lag, 1) if lag else None,
                'has_evac': has_evac,
            })
        fire_points[county] = pts

        summaries[county] = {
            'county': county,
            'svi': round(float(svi_row.get('rpl_themes') or 0), 4),
            'total_fires': len(fires),
            'evac_fires': len(evac_fires),
            'median_lag': round(statistics.median(lags), 2) if lags else None,
            'ep_noint': round(float(svi_row.get('ep_noint') or 0), 1),
            'ep_noveh': round(float(svi_row.get('ep_noveh') or 0), 1),
            'ep_age65': round(float(svi_row.get('ep_age65') or 0), 1),
            'ep_limeng': round(float(svi_row.get('ep_limeng') or 0), 1),
            'ep_disabl': round(float(svi_row.get('ep_disabl') or 0), 1),
            'ep_pov150': round(float(svi_row.get('ep_pov150') or 0), 1),
            'top_fires': top_fires,
        }
    return summaries, fire_points, 0.83

COUNTY_DATA, FIRE_POINTS, CA_MEDIAN = load_county_data()
COUNTY_NAMES = sorted(COUNTY_DATA.keys())

# Build FIPS → county name lookup once at startup
FIPS_TO_COUNTY = {}
try:
    import urllib.request, json as _json
    _url = 'https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json'
    with urllib.request.urlopen(_url, timeout=10) as _r:
        _gj = _json.load(_r)
    for _feat in _gj.get('features', []):
        if _feat['id'].startswith('06'):
            _name = _feat['properties']['NAME'] + ' County'
            if _name in COUNTY_DATA:
                FIPS_TO_COUNTY[_feat['id']] = _name
    print(f'[app] FIPS lookup built: {len(FIPS_TO_COUNTY)} counties')
except Exception as _e:
    print(f'[app] FIPS lookup failed: {_e}')

# ── Helpers ───────────────────────────────────────────────────────────────────

def svi_color(svi):
    if svi >= 0.60:
        return {'color': '#A32D2D', 'bg': '#FCEBEB', 'label': 'High',
                'desc': f'SVI: {svi:.2f} · top 25% most vulnerable in CA'}
    if svi >= 0.50:
        return {'color': '#854F0B', 'bg': '#FAEEDA', 'label': 'Medium-high',
                'desc': f'SVI: {svi:.2f} · above CA average'}
    if svi >= 0.42:
        return {'color': '#BA7517', 'bg': '#FEF3CD', 'label': 'Medium-low',
                'desc': f'SVI: {svi:.2f} · near CA average'}
    return {'color': '#3B6D11', 'bg': '#EAF3DE', 'label': 'Low',
            'desc': f'SVI: {svi:.2f} · below CA average'}

def lag_color(lag):
    if lag is None: return '#888780'
    if lag > CA_MEDIAN * 3: return '#A32D2D'
    if lag > CA_MEDIAN: return '#854F0B'
    return '#3B6D11'

def indicator_color(val):
    if val > 20: return '#A32D2D'
    if val > 10: return '#854F0B'
    return '#3B6D11'

def recommend_alert(severity, svi, is_night):
    """
    Historical escalation-pattern lookup (NOT a live recommendation).

    Given a fire's characteristics, this returns how *similar fires were handled
    historically* in California (2021-2025), as a planning reference — it does
    not tell anyone what to do about a live fire.

    Layer 1 — Base pattern from historical evacuation rates:
      Minor    fires: ~0.2% historically escalated to evacuation  → rarely evacuated
      Moderate fires: ~3.8% historically escalated                → sometimes advisory
      Major    fires: ~16.3% historically escalated               → often warned
      Extreme  fires: ~44.7% historically escalated               → usually ordered

    Layer 2 — Observed associations in the historical data:
      In high-vulnerability counties (SVI >= 0.60), fires historically showed
      longer alert lags; night fires in those counties escalated more often than
      severity alone would suggest. These are descriptive patterns for planners
      to weigh — not an automatic escalation of any live alert.
    """
    high_vuln = svi >= 0.60
    levels = ['Historically rarely evacuated', 'Historically: often advisory',
              'Historically: often warned', 'Historically: usually ordered']
    colors = ['#888780', '#BA7517', '#854F0B', '#A32D2D']
    bgs    = ['#f5f5f3', '#FEF3CD', '#FAEEDA', '#FCEBEB']
    notes  = [
        'Historically, only ~0.2% of minor-severity fires in this dataset escalated to evacuation.',
        'Historically, ~3.8% of moderate-severity fires in this dataset escalated to evacuation.',
        'Historically, ~16.3% of major-severity fires in this dataset escalated to evacuation.',
        'Historically, ~44.7% of extreme-severity fires in this dataset escalated to evacuation.',
    ]

    base_idx = {'Minor': 0, 'Moderate': 1, 'Major': 2, 'Extreme': 3}.get(severity, 1)
    idx = base_idx
    escalation_reasons = []

    # Layer 2a: SVI adjustment
    if high_vuln and idx < 3:
        idx += 1
        escalation_reasons.append(
            f'Note for planners: SVI {svi:.2f} ≥ 0.60 — fires in this high-vulnerability '
            f'county historically showed longer alert lags, and escalated more often '
            f'than severity alone would suggest.'
        )

    # Layer 2b: Night fire + high SVI
    if is_night and high_vuln and idx < 3:
        idx += 1
        escalation_reasons.append(
            'Note for planners: night fires in high-vulnerability counties historically '
            'escalated more often — compounded access barriers (no internet, no vehicle, '
            'limited English) are harder to overcome at night.'
        )

    return {
        'level':   levels[idx],
        'color':   colors[idx],
        'bg':      bgs[idx],
        'note':    notes[idx],
        'base_level': levels[base_idx],
        'escalated': idx > base_idx,
        'escalation_reasons': escalation_reasons,
    }

def affected_population(county_name):
    if county_name not in COUNTY_DATA:
        return []
    d = COUNTY_DATA[county_name]
    return [
        ('Aged 65+',        d['ep_age65']),
        ('No vehicle',      d['ep_noveh']),
        ('No internet',     d['ep_noint']),
        ('Limited English', d['ep_limeng']),
        ('Disability',      d['ep_disabl']),
    ]

# ── Map ───────────────────────────────────────────────────────────────────────

def build_map(selected_county=None):
    geojson_url = 'https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json'
    try:
        geojson = requests.get(geojson_url, timeout=5).json()
        geojson['features'] = [f for f in geojson['features'] if f['id'].startswith('06')]
    except:
        geojson = {'type': 'FeatureCollection', 'features': []}

    fips_svi, fips_name = {}, {}
    for county, d in COUNTY_DATA.items():
        name_clean = county.replace(' County', '')
        lag_str = f"{d['median_lag']:.1f} hrs" if d['median_lag'] else 'No evac data'
        for feat in geojson.get('features', []):
            if feat.get('properties', {}).get('NAME', '').lower() == name_clean.lower():
                fips_svi[feat['id']] = d['svi']
                fips_name[feat['id']] = f"{county}<br>SVI: {d['svi']:.2f}<br>Alert lag: {lag_str}"

    fips_list = list(fips_svi.keys())
    fig = go.Figure(go.Choropleth(
        geojson=geojson, locations=fips_list,
        z=[fips_svi[f] for f in fips_list],
        text=[fips_name.get(f, '') for f in fips_list],
        hovertemplate='%{text}<extra></extra>',
        colorscale=[[0.0,'#EAF3DE'],[0.42,'#FEF3CD'],[0.55,'#FAEEDA'],
                    [0.70,'#F7C1C1'],[1.0,'#A32D2D']],
        zmin=0, zmax=0.85, showscale=False,
        marker_line_width=0.5, marker_line_color='white',
    ))

    if selected_county and selected_county in COUNTY_DATA:
        name_clean = selected_county.replace(' County', '')
        for feat in geojson.get('features', []):
            if feat.get('properties', {}).get('NAME', '').lower() == name_clean.lower():
                fig.add_trace(go.Choropleth(
                    geojson=geojson, locations=[feat['id']], z=[1],
                    colorscale=[[0,'rgba(0,0,0,0)'],[1,'rgba(0,0,0,0)']],
                    showscale=False, marker_line_width=3,
                    marker_line_color='#1a1a1a', hoverinfo='skip',
                ))

    fig.update_layout(
        geo=dict(scope='usa', projection_type='albers usa', showlakes=False,
                 bgcolor='rgba(0,0,0,0)', fitbounds='locations'),
        margin=dict(l=0, r=100, t=0, b=0),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        height=420, clickmode='event+select',
    )
    return fig

# ── Report card ───────────────────────────────────────────────────────────────

def build_report_card(county_name):
    if not county_name or county_name not in COUNTY_DATA:
        return html.Div('Click a county on the map to view its report.',
                        style={'color':'#888780','fontSize':'14px',
                               'padding':'40px','textAlign':'center'})
    d = COUNTY_DATA[county_name]
    vc = svi_color(d['svi'])
    lc = lag_color(d['median_lag'])
    lag_text = f"{d['median_lag']:.1f} hrs" if d['median_lag'] else 'No evacuation data'
    max_lag = 45.0
    lag_pct = min((d['median_lag'] or 0) / max_lag * 100, 100)
    ca_pct = min(CA_MEDIAN / max_lag * 100, 100)

    indicators = sorted([
        {'label':'No internet access','val':d['ep_noint']},
        {'label':'No vehicle',        'val':d['ep_noveh']},
        {'label':'Aged 65+',          'val':d['ep_age65']},
        {'label':'Limited English',   'val':d['ep_limeng']},
        {'label':'Disability',        'val':d['ep_disabl']},
        {'label':'Below poverty (150%)','val':d['ep_pov150']},
    ], key=lambda x: x['val'], reverse=True)

    fire_rows = []
    for f in (d['top_fires'] or []):
        lag_str = f"{f['lag']:.1f} hrs" if f['lag'] else 'No evac order'
        fire_rows.append(html.Div([
            html.Div([
                html.Div(f['name'], style={'fontSize':'13px','fontWeight':'500'}),
                html.Div(f"{f['date']} · {f['acres']:,.0f} acres",
                         style={'fontSize':'11px','color':'#888780'}),
            ]),
            html.Div(lag_str, style={'fontSize':'12px','fontWeight':'500',
                                     'color':lag_color(f['lag'])}),
        ], style={'display':'flex','justifyContent':'space-between',
                  'alignItems':'center','padding':'6px 0',
                  'borderBottom':'0.5px solid #f0f0f0'}))

    # Recommended actions — policy format
    actions = []

    # Use fire history to make recommendations more specific
    n_fires = d['total_fires']
    n_evac = d['evac_fires']
    evac_rate = round(n_evac / n_fires * 100, 1) if n_fires > 0 else 0
    top_fire = d['top_fires'][0] if d['top_fires'] else None

    if d['ep_noint'] > 20:
        actions.append({
            'title': 'Establish non-digital alert backup',
            'why': f"{d['ep_noint']:.0f}% of households have no internet and will not receive Watch Duty alerts.",
            'rec': f"Before fire season, work with the county emergency communications office to establish reverse-911 calls and AM radio broadcasts as backup channels alongside the Watch Duty app, and test them. With {n_fires} fires recorded in this county since 2021, a reliable backup channel is a worthwhile planning investment.",
        })

    if d['ep_noveh'] > 10:
        top_fire_note = f" During {top_fire['name']} ({top_fire['date']}), for example, residents without vehicles would have had no independent means of leaving." if top_fire else ''
        actions.append({
            'title': 'Set up evacuation transport for car-free households',
            'why': f"{d['ep_noveh']:.0f}% of households have no vehicle and cannot leave on their own.",
            'rec': f"Before fire season, work with the county transit authority to identify car-free households in high-fire-risk areas and pre-register them for priority pickup.{top_fire_note} Pre-designate pickup points in neighborhoods with the highest concentration of car-free residents.",
        })

    if d['ep_limeng'] > 8:
        actions.append({
            'title': 'Prepare evacuation materials in multiple languages',
            'why': f"{d['ep_limeng']:.0f}% of residents have limited English proficiency.",
            'rec': f"Before fire season, prepare evacuation route maps and shelter information in the languages most spoken in this county, and pre-position them through community organizations, ethnic media outlets, and multilingual social media. Historically {evac_rate}% of fires in this county escalated to evacuation orders, so having these materials ready is a useful planning step.",
        })

    if d['ep_age65'] > 20:
        actions.append({
            'title': 'Assign welfare check teams for elderly residents',
            'why': f"{d['ep_age65']:.0f}% of residents are aged 65 or older and may need help evacuating.",
            'rec': f"Before fire season, work with the county health department to map elderly households in fire-prone areas and pre-establish welfare-check team protocols so flagged addresses can be reached quickly during an evacuation. This county has recorded {n_fires} fires since 2021.",
        })

    if d['ep_disabl'] > 15:
        actions.append({
            'title': 'Update the Access and Functional Needs registry',
            'why': f"{d['ep_disabl']:.0f}% of residents have a disability that may affect how quickly they can evacuate.",
            'rec': f"Keep the county's Access and Functional Needs registry current and cross-referenced with evacuation-zone maps before fire season, so outreach can reach registered addresses quickly when an evacuation occurs.",
        })

    if d['median_lag'] and d['median_lag'] > CA_MEDIAN * 2:
        top_fire_lag = f" The longest recorded lag in this county was {d['top_fires'][0]['lag']:.1f} hours during {d['top_fires'][0]['name']}." if top_fire and top_fire.get('lag') else ''
        actions.append({
            'title': "Flag this county's historically long alert lags for planning review",
            'why': f"Evacuation alerts in this county take {d['median_lag']:.1f} hours on average — {d['median_lag']/CA_MEDIAN:.1f}× longer than the California median of {CA_MEDIAN:.1f} hours.{top_fire_lag}",
            'rec': f"This county's historically long alert lags ({d['median_lag']/CA_MEDIAN:.1f}× the CA median) are a planning consideration. Given the higher vulnerability of its population, jurisdictions may wish to review — during planning, not live response — whether earlier advisory thresholds would give residents more time.",
        })

    if not actions:
        actions.append({
            'title': 'Continue monitoring — vulnerability profile is below CA average',
            'why': f"This county's vulnerability indicators are all below the California average, and its {n_fires} recorded fires since 2021 have a {evac_rate}% evacuation rate.",
            'rec': 'Keep current emergency protocols in place. Re-assess if vulnerability scores or alert lag increases significantly in future reporting cycles.',
        })

    card_style = {
        'background':'white','border':'1px solid #d0ccc4',
        'borderRadius':'4px','padding':'18px 22px','marginBottom':'12px',
        'boxShadow':'0 1px 3px rgba(0,0,0,0.06)',
    }
    section_style = {
        'marginBottom':'16px','paddingBottom':'16px',
        'borderBottom':'1px solid #e8e4dc',
    }

    return html.Div([

        # Card 1: data
        html.Div([
            # Header
            html.Div([
                html.Div([
                    html.Div(county_name, style={'fontSize':'20px','fontWeight':'700',
                                              'fontFamily':'-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,sans-serif',
                                              'letterSpacing':'0.01em'}),
                    html.Div('California · Wildfire Equity Report',
                             style={'fontSize':'12px','color':'#888780','marginTop':'2px'}),
                ]),
                html.Div([
                    html.Div(vc['label'], style={'fontSize':'22px','fontWeight':'500',
                                                  'color':vc['color'],'textAlign':'right'}),
                    html.Div(vc['desc'], style={'fontSize':'11px','color':vc['color'],
                                                'textAlign':'right','marginTop':'2px'}),
                ]),
            ], style={'display':'flex','justifyContent':'space-between',
                      'alignItems':'flex-start','marginBottom':'16px',
                      'paddingBottom':'14px','borderBottom':'0.5px solid #e8e8e8'}),

            # Alert lag
            html.Div([
                html.Div('⏱ Time to Evacuation Alert',
                         style={'fontSize':'10px','color':'#444','fontWeight':'700',
                                'textTransform':'uppercase','letterSpacing':'0.08em',
                                'marginBottom':'10px','fontFamily':'-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,sans-serif',
                                'borderLeft':'3px solid #E24B4A','paddingLeft':'8px'}),
                html.Div([
                    html.Span('This county (median)', style={'fontSize':'13px','color':'#666'}),
                    html.Span(lag_text, style={'fontSize':'13px','fontWeight':'700','color':lc,
                                               'fontFamily':'-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,sans-serif'}),
                ], style={'display':'flex','justifyContent':'space-between','marginBottom':'8px'}),
                *[html.Div([
                    html.Div(label, style={'fontSize':'11px','color':'#666',
                                           'width':'80px','flexShrink':'0'}),
                    html.Div(html.Div(style={'width':f'{pct}%','height':'100%',
                                             'background':color,'borderRadius':'2px'}),
                             style={'flex':'1','height':'10px','background':'#e8e4dc',
                                    'borderRadius':'2px','overflow':'hidden'}),
                    html.Div(val_text, style={'fontSize':'11px','fontWeight':'700',
                                              'color':color,'width':'55px',
                                              'textAlign':'right','flexShrink':'0'}),
                ], style={'display':'flex','alignItems':'center','gap':'8px','marginBottom':'6px'})
                for label, pct, color, val_text in [
                    ('This county', lag_pct, lc, lag_text),
                    ('CA median', ca_pct, '#3B6D11', f'{CA_MEDIAN:.1f} hrs'),
                ]],
            ], style=section_style),

            # Community vulnerability + major fires side by side
            html.Div([
                html.Div([
                    html.Div('👥 Community Vulnerability',
                             style={'fontSize':'10px','color':'#444','fontWeight':'700',
                                    'textTransform':'uppercase','letterSpacing':'0.08em',
                                    'marginBottom':'10px','fontFamily':'-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,sans-serif',
                                    'borderLeft':'3px solid #E24B4A','paddingLeft':'8px'}),
                    *[html.Div([
                        html.Span(ind['label'], style={'fontSize':'12px','color':'#444'}),
                        html.Span(f"{ind['val']:.1f}%",
                                  style={'fontSize':'12px','fontWeight':'700',
                                         'color':indicator_color(ind['val']),
                                         'fontFamily':'-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,sans-serif'}),
                    ], style={'display':'flex','justifyContent':'space-between',
                              'padding':'5px 0','borderBottom':'1px solid #e8e4dc'})
                    for ind in indicators],
                ], style={'flex':'1','minWidth':'0','paddingRight':'16px',
                          'borderRight':'1px solid #e8e4dc'}),

                html.Div([
                    html.Div('🔥 Major Fires (2021–2025)',
                             style={'fontSize':'10px','color':'#444','fontWeight':'700',
                                    'textTransform':'uppercase','letterSpacing':'0.08em',
                                    'marginBottom':'10px','fontFamily':'-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,sans-serif',
                                    'borderLeft':'3px solid #E24B4A','paddingLeft':'8px'}),
                    html.Div([
                        html.Span('Total fires recorded',
                                  style={'fontSize':'12px','color':'#666'}),
                        html.Span(f"{d['total_fires']:,}",
                                  style={'fontSize':'12px','fontWeight':'700',
                                         'fontFamily':'-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,sans-serif'}),
                    ], style={'display':'flex','justifyContent':'space-between',
                              'marginBottom':'8px'}),
                    *fire_rows,
                ], style={'flex':'1','minWidth':'0','paddingLeft':'16px'}),

            ], style={'display':'flex','gap':'0'}),

        ], style=card_style),

        # Card 2: recommended actions
        html.Div([
            html.Div('Pre-Season Planning Recommendations',
                     style={'fontSize':'13px','fontWeight':'700','marginBottom':'16px',
                            'fontFamily':'-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,sans-serif','letterSpacing':'0.01em',
                            'borderLeft':'3px solid #E24B4A','paddingLeft':'8px'}),
            *[html.Div([
                html.Div([
                    html.Div(str(i+1), style={
                        'width':'22px','height':'22px','borderRadius':'2px',
                        'background':'#1a1a1a','color':'white','fontSize':'11px',
                        'fontWeight':'700','display':'flex','alignItems':'center',
                        'justifyContent':'center','flexShrink':'0',
                        'fontFamily':'-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,sans-serif',
                    }),
                    html.Div(action['title'],
                             style={'fontSize':'13px','fontWeight':'700','color':'#1a1a1a',
                                    'fontFamily':'-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,sans-serif','lineHeight':'1.4'}),
                ], style={'display':'flex','gap':'10px','alignItems':'flex-start',
                          'marginBottom':'6px'}),
                html.Div(action['why'],
                         style={'fontSize':'12px','color':'#666','lineHeight':'1.5',
                                'marginBottom':'6px','paddingLeft':'32px',
                                'fontStyle':'italic'}),
                html.Div([
                    html.Span('Recommended: ',
                              style={'fontWeight':'700','color':'#1a1a1a','fontSize':'12px'}),
                    html.Span(action['rec'],
                              style={'fontSize':'12px','color':'#444','lineHeight':'1.6'}),
                ], style={'paddingLeft':'32px','marginBottom':'2px'}),
            ], style={
                'marginBottom':'16px','paddingBottom':'16px',
                'borderBottom':'1px solid #e8e4dc',
            }) for i, action in enumerate(actions)],
        ], style=card_style),

    ])

# ── Tab 2: fire assessment ────────────────────────────────────────────────────

def build_tab2():
    return html.Div([
        html.Div([

            # Left: input form
            html.Div([
                html.Div('Historical fire-response lookup',
                         style={'fontSize':'15px','fontWeight':'500','marginBottom':'4px'}),
                html.Div('Enter fire characteristics to see how fires with a similar profile were handled historically in this county — for pre-season planning, not live dispatch.',
                         style={'fontSize':'12px','color':'#888780','marginBottom':'20px'}),

                html.Div('County *', style={'fontSize':'12px','color':'#555','marginBottom':'6px'}),
                dcc.Dropdown(
                    id='t2-county',
                    options=[{'label': c, 'value': c} for c in COUNTY_NAMES],
                    placeholder='Select county...',
                    style={'marginBottom':'16px','fontSize':'13px'},
                ),

                html.Div('Visual severity *',
                         style={'fontSize':'12px','color':'#555','marginBottom':'6px'}),
                html.Div([
                    *[html.Label([
                        dcc.RadioItems(
                            id='t2-severity',
                            options=[
                                {'label': ' Minor — under ~10 acres', 'value': 'Minor'},
                                {'label': ' Moderate — ~10–100 acres', 'value': 'Moderate'},
                                {'label': ' Major — ~100–1,000 acres', 'value': 'Major'},
                                {'label': ' Extreme — 1,000+ acres', 'value': 'Extreme'},
                            ],
                            value='Moderate',
                            labelStyle={'display':'block','fontSize':'13px',
                                        'marginBottom':'8px','cursor':'pointer'},
                        ),
                    ])],
                ], style={'marginBottom':'16px'}),

                html.Div('Time of report',
                         style={'fontSize':'12px','color':'#555','marginBottom':'6px'}),
                html.Div([
                    dcc.Checklist(
                        id='t2-time',
                        options=[{'label': ' Night fire (9pm – 6am)', 'value': 'night'}],
                        value=[],
                        style={'fontSize':'13px'},
                        labelStyle={'cursor':'pointer'},
                    ),
                    html.Div('In this historical dataset, night fires in high-vulnerability counties escalated more often — reflected in the pattern shown.',
                             style={'fontSize':'11px','color':'#888780','marginTop':'4px',
                                    'lineHeight':'1.4'}),
                ], style={'marginBottom':'20px'}),

                html.Button('Show historical pattern →', id='t2-submit', n_clicks=0,
                            style={'width':'100%','padding':'10px','fontSize':'13px',
                                   'fontWeight':'500','cursor':'pointer',
                                   'background':'#E24B4A','color':'white',
                                   'border':'none','borderRadius':'8px'}),

            ], style={
                'width':'280px','flexShrink':'0',
                'background':'white','border':'0.5px solid #e8e8e8',
                'borderRadius':'12px','padding':'20px',
            }),

            # Right: output
            html.Div(
                id='t2-output',
                children=html.Div(
                    'Fill in the form and click "Show historical pattern" to see how similar fires were handled historically.',
                    style={'color':'#888780','fontSize':'14px',
                           'padding':'40px','textAlign':'center'}
                ),
                style={'flex':'1','minWidth':'0'},
            ),

        ], style={'display':'flex','gap':'20px','alignItems':'flex-start',
                  'padding':'20px 48px'}),
    ])

# ── Layout ────────────────────────────────────────────────────────────────────

app = dash.Dash(__name__, title='Wildfire Equity Audit · California')

TOPBAR = html.Div([
    html.Div([
        html.Div('🔥', style={'width':'32px','height':'32px','background':'#E24B4A',
                               'borderRadius':'8px','display':'flex',
                               'alignItems':'center','justifyContent':'center',
                               'fontSize':'16px'}),
        html.Div([
            html.Div('Wildfire Equity Audit',
                     style={'fontSize':'15px','fontWeight':'700','color':'white',
                            'fontFamily':'-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,sans-serif','letterSpacing':'0.02em'}),
            html.Div('California · 2021–2025',
                     style={'fontSize':'12px','color':'#aaa'}),
        ]),
    ], style={'display':'flex','alignItems':'center','gap':'10px'}),
    html.Div('WiDS Datathon 2026',
             style={'fontSize':'11px','padding':'4px 10px','background':'#FCEBEB',
                    'color':'#A32D2D','borderRadius':'20px','fontWeight':'500'}),
], style={'display':'flex','justifyContent':'space-between','alignItems':'center',
          'padding':'14px 24px','borderBottom':'2px solid #1a1a1a','background':'#1a1a1a'})

app.layout = html.Div([
    TOPBAR,

    # Nav tabs
    html.Div([
        html.Div(id='nav-1', children='1 — County report card',
                 style={'fontSize':'13px','fontWeight':'600','color':'white',
                        'borderBottom':'3px solid #E24B4A','paddingBottom':'10px',
                        'marginBottom':'-2px','cursor':'pointer',
                        'fontFamily':'-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,sans-serif','letterSpacing':'0.01em'}),
        html.Div(id='nav-2', children='2 — Historical response patterns',
                 style={'fontSize':'13px','color':'#aaa',
                        'paddingBottom':'10px','cursor':'pointer'}),
    ], style={'display':'flex','gap':'24px','padding':'0 24px',
              'borderBottom':'2px solid #2c2c2c','background':'#2c2c2c'}),

    dcc.Store(id='active-tab', data='1'),

    # Tab 1 content
    html.Div(id='tab1-content', children=[
        html.Div([
            html.Div([
                html.Div('Click a county to view its report',
                         style={'fontSize':'12px','color':'#888780','marginBottom':'8px'}),
                dcc.Graph(id='ca-map', figure=build_map(),
                          config={'displayModeBar':False}, style={'height':'420px'}),
                html.Div([
                    html.Div('Vulnerability:',
                             style={'fontSize':'11px','color':'#888780','marginRight':'8px'}),
                    *[html.Div(label, style={
                        'fontSize':'11px','padding':'2px 8px','background':bg,
                        'color':color,'borderRadius':'20px','fontWeight':'500',
                    }) for label, color, bg in [
                        ('Low','#3B6D11','#EAF3DE'),
                        ('Medium-low','#BA7517','#FEF3CD'),
                        ('Medium-high','#854F0B','#FAEEDA'),
                        ('High','#A32D2D','#FCEBEB'),
                    ]],
                ], style={'display':'flex','alignItems':'center','gap':'6px',
                          'marginTop':'8px','flexWrap':'wrap'}),
            ], style={'flex':'1','minWidth':'0'}),
            html.Div(id='report-card',
                     children=html.Div(
                         'Click a county on the map to view its report.',
                         style={'color':'#888780','fontSize':'14px','padding':'40px',
                                'textAlign':'center','border':'0.5px solid #e8e8e8',
                                'borderRadius':'12px','background':'white'}),
                     style={'width':'460px','flexShrink':'0','marginLeft':'20px'}),
        ], style={'display':'flex','gap':'20px','padding':'20px 24px 20px 16px',
                  'alignItems':'flex-start'}),
    ]),

    # Tab 2 content
    html.Div(id='tab2-content', children=build_tab2(), style={'display':'none'}),

    # Tab 3 placeholder removed

    # Footer
    html.Div('Data sources: WatchDuty (2021–2025) · CDC/ATSDR Social Vulnerability Index 2022 · ACS 2018–2022',
             style={'fontSize':'11px','color':'#888','textAlign':'center',
                    'padding':'14px','borderTop':'2px solid #2c2c2c',
                    'background':'#1a1a1a','color':'#aaa',
                    'fontFamily':'-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,sans-serif','letterSpacing':'0.02em'}),

], style={'fontFamily':'-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,sans-serif',
          'background':'#f4f2ed','minHeight':'100vh'})

# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output('report-card','children'),
    Output('ca-map','figure'),
    Input('ca-map','clickData'),
)
def update_report(click_data):
    selected = None
    if click_data:
        point = click_data['points'][0]
        loc = point.get('location', '')
        if loc and loc in FIPS_TO_COUNTY:
            selected = FIPS_TO_COUNTY[loc]
        if not selected:
            text = point.get('text', '')
            if text:
                candidate = text.split('<br>')[0]
                if candidate in COUNTY_DATA:
                    selected = candidate

    return build_report_card(selected), build_map(selected)


@callback(
    Output('tab1-content','style'),
    Output('tab2-content','style'),
    Output('nav-1','style'),
    Output('nav-2','style'),
    Output('active-tab','data'),
    Input('nav-1','n_clicks'),
    Input('nav-2','n_clicks'),
    State('active-tab','data'),
    prevent_initial_call=True,
)
def switch_tab(n1, n2, active):
    from dash import ctx
    triggered = ctx.triggered_id
    tab = '1' if triggered == 'nav-1' else '2'

    show = {'display':'block'}
    hide = {'display':'none'}
    active_nav = {'fontSize':'13px','fontWeight':'600','color':'white',
                  'borderBottom':'3px solid #E24B4A','paddingBottom':'10px',
                  'marginBottom':'-2px','cursor':'pointer'}
    inactive_nav = {'fontSize':'13px','color':'#aaa',
                    'paddingBottom':'10px','cursor':'pointer'}

    return (
        show if tab=='1' else hide,
        show if tab=='2' else hide,
        active_nav if tab=='1' else inactive_nav,
        active_nav if tab=='2' else inactive_nav,
        tab,
    )


@callback(
    Output('t2-output','children'),
    Input('t2-submit','n_clicks'),
    State('t2-county','value'),
    State('t2-severity','value'),
    State('t2-time','value'),
    prevent_initial_call=True,
)
def assess_fire(n_clicks, county, severity, night_check):
    if not county or not severity:
        return html.Div('Please fill in county and severity.',
                        style={'color':'#A32D2D','fontSize':'13px','padding':'20px'})

    svi = COUNTY_DATA[county]['svi'] if county in COUNTY_DATA else 0.5
    is_night = bool(night_check and 'night' in night_check)
    vc = svi_color(svi)
    rec = recommend_alert(severity, svi, is_night)
    pop = affected_population(county)

    severity_acres = {
        'Minor': '< 10 acres',
        'Moderate': '10–100 acres',
        'Major': '100–1,000 acres',
        'Extreme': '1,000+ acres',
    }

    card_style = {
        'background':'white','border':'1px solid #d0ccc4',
        'borderRadius':'4px','padding':'18px 22px','marginBottom':'12px',
        'boxShadow':'0 1px 3px rgba(0,0,0,0.06)',
    }

    return html.Div([

        # Alert recommendation
        html.Div([
            html.Div([
                html.Div([
                    html.Div(county, style={'fontSize':'16px','fontWeight':'600'}),
                    html.Span('Vulnerability: ',
                              style={'fontSize':'12px','color':'#666'}),
                    html.Span(vc['label'],
                              style={'fontSize':'12px','fontWeight':'600',
                                     'color':vc['color']}),
                ]),
                html.Div('Based on CA historical fire data (2021–2025)',
                         style={'fontSize':'11px','color':'#888780'}),
            ], style={'marginBottom':'16px','paddingBottom':'14px',
                      'borderBottom':'1px solid #e8e4dc'}),

            html.Div('Historical escalation pattern',
                     style={'fontSize':'10px','color':'#444','fontWeight':'700',
                            'textTransform':'uppercase','letterSpacing':'0.08em',
                            'marginBottom':'8px','borderLeft':'3px solid #E24B4A',
                            'paddingLeft':'8px'}),

            html.Div([
                html.Div([
                    html.Div(rec['level'],
                             style={'fontSize':'22px','fontWeight':'700',
                                    'color':rec['color']}),
                    html.Div(
                        f"Base pattern: {rec['base_level']} — fires like this in high-vulnerability / night conditions historically escalated more often",
                        style={'fontSize':'11px','color':rec['color'],
                               'marginTop':'2px','fontStyle':'italic'}
                    ) if rec['escalated'] else html.Div(
                        f"Based on historical {severity.lower()}-severity fires",
                        style={'fontSize':'11px','color':'#666','marginTop':'2px'}
                    ),
                ]),
            ], style={'background':rec['bg'],'borderRadius':'4px',
                      'padding':'12px 16px','marginBottom':'10px',
                      'border':f"1px solid {rec['color']}22"}),

            html.Div(rec['note'],
                     style={'fontSize':'12px','color':'#444','lineHeight':'1.6',
                            'marginBottom':'10px'}),

            # Escalation reasons
            *[html.Div([
                html.Span('↑ ', style={'color':rec['color'],'fontWeight':'700'}),
                html.Span(reason, style={'fontSize':'11px','color':'#555',
                                         'lineHeight':'1.5'}),
            ], style={'background':rec['bg'],'borderRadius':'4px',
                      'padding':'8px 12px','marginBottom':'6px',
                      'borderLeft':f"3px solid {rec['color']}"})
            for reason in rec['escalation_reasons']],

        ], style=card_style),

        # Estimated fire size + affected population
        html.Div([
            html.Div([
                html.Div([
                    html.Div('Estimated fire size',
                             style={'fontSize':'11px','color':'#888780',
                                    'textTransform':'uppercase','letterSpacing':'0.05em',
                                    'marginBottom':'6px'}),
                    html.Div(severity_acres.get(severity,'—'),
                             style={'fontSize':'18px','fontWeight':'500'}),
                    html.Div(f"Based on {severity.lower()} severity fires in CA",
                             style={'fontSize':'11px','color':'#888780','marginTop':'2px'}),
                ], style={'flex':'1','paddingRight':'16px',
                          'borderRight':'0.5px solid #e8e8e8'}),

                html.Div([
                    html.Div('County demographic profile (CDC SVI / ACS)',
                             style={'fontSize':'11px','color':'#888780',
                                    'textTransform':'uppercase','letterSpacing':'0.05em',
                                    'marginBottom':'8px'}),
                    *[html.Div([
                        html.Span(label, style={'fontSize':'12px','color':'#555'}),
                        html.Span(f"{val:.1f}%",
                                  style={'fontSize':'12px','fontWeight':'500',
                                         'color':indicator_color(val)}),
                    ], style={'display':'flex','justifyContent':'space-between',
                              'padding':'4px 0','borderBottom':'0.5px solid #f0f0f0'})
                    for label, val in sorted(pop, key=lambda x: x[1], reverse=True)],
                ], style={'flex':'1','paddingLeft':'16px'}),

            ], style={'display':'flex','gap':'0'}),
        ], style=card_style),

        # Night fire note
        html.Div([
            html.Div('🌙 Night fire' if is_night else '☀️ Daytime fire',
                     style={'fontSize':'13px','fontWeight':'600','marginBottom':'4px'}),
            html.Div(
                'Night fire in a high-vulnerability county — historically these escalated more often (reflected above).' if is_night
                else 'Daytime fire. Historical pattern shown above.',
                style={'fontSize':'12px','color':'#555','lineHeight':'1.5'}
            ),
        ], style={**card_style,
                  'background':'#f0f4ff' if is_night else '#f5f5f3',
                  'border':'0.5px solid #c8d4f0' if is_night else '0.5px solid #e8e8e8'}),

    ])


if __name__ == '__main__':
    app.run(debug=True, port=8050)
