import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, dcc, html, callback, ctx
from dash.exceptions import PreventUpdate
from dash import ALL
import re
import uuid
import numpy as np
from dataclasses import dataclass, asdict, field
from pydantic.dataclasses import dataclass
import dash_ag_grid as dag
import pandas as pd
import time
# Debug only
import json

# -----------------------------------------------
# Globals (template parameters common to all runs)
# upstream of all instance-specific data. Sharing between sessions
# is expected to be okay but should be verified
# -----------------------------------------------

### --- CONSTANTS --- ###

# Dev only = static precip values to develop the logic for calculating
# C-values in the areas, then aggregating them to their basins
DEV_PRECIP = {
    "WQE": 0.6,
    "2-yr": 0.812,
    "5-yr": 1.07,
    "10-yr": 1.31,
    "25-yr": 1.66,
    "50-yr": 1.95,
    "100-yr": 2.27,
    "500-yr": 3.09,
}

precip_cols = ['WQE', '2-yr', '5-yr', '10-yr', '25-yr', '50-yr', '100-yr', '500-yr']

area_cols_fld = [
    {'field': 'Area'},
    {'field': 'Soil Type'},
    {'field': '% Impervious'},
    {'field': 'C WQE'},
    {'field': 'C 2-yr'},
    {'field': 'C 5-yr'},
    {'field': 'C 10-yr'},
    {'field': 'C 25-yr'},
    {'field': 'C 50-yr'},
    {'field': 'C 100-yr'},
    {'field': 'C 500-yr'},
    {'field': 'id'},
    {'field': 'time_created'},
    {'field': 'basin_id'}
]

basin_cols_fld = [
    {'field': 'Name'},
    {'field': 'Area'},
    {'field': 'Soils'},
    {'field': 'L_i'},
    {'field': 'S_i'},
    {'field': 'L_t'},
    {'field': 'S_t'},
    {'field': 'NRCS_K'},
    {'field': 'Imperviousness'},
    {'field': 't_c_basin'},
    {'field': 't_c_regional'},
    {'field': 't_c_effective'},
    {'field': 't_c_override'},
    {'field': 't_i'},
    {'field': 'channel_flow_velocity'},
    {'field': 't_t'},
    # Rainfall intensity
    {'field': 'I WQE'},
    {'field': 'I 2-yr'},
    {'field': 'I 5-yr'},
    {'field': 'I 10-yr'},
    {'field': 'I 25-yr'},
    {'field': 'I 50-yr'},
    {'field': 'I 100-yr'},
    {'field': 'I 500-yr'},
    # Runoff Coefficient
    {'field': 'C WQE'},
    {'field': 'C 2-yr'},
    {'field': 'C 5-yr'},
    {'field': 'C 10-yr'},
    {'field': 'C 25-yr'},
    {'field': 'C 50-yr'},
    {'field': 'C 100-yr'},
    {'field': 'C 500-yr'},
    # Discharge
    {'field': 'Q WQE'},
    {'field': 'Q 2-yr'},
    {'field': 'Q 5-yr'},
    {'field': 'Q 10-yr'},
    {'field': 'Q 25-yr'},
    {'field': 'Q 50-yr'},
    {'field': 'Q 100-yr'},
    {'field': 'Q 500-yr'},
    {'field': 'href'},
    {'field': 'id'},
]


# -----------------------------------------------
# Non-Callback Functions
# -----------------------------------------------



# Calculate runoff coefficients per the MHFD Criteria Manual
def get_c_values(soil, imperv):
    match soil:
        case 'A':
            cWQE = 0.840 * (imperv ** 1.302)
            c002 = 0.840 * (imperv ** 1.302)
            c005 = 0.861 * (imperv ** 1.276)
            c010 = 0.873 * (imperv ** 1.232)
            c025 = 0.884 * (imperv ** 1.124)
            c050 = (0.854 * imperv) + 0.025
            c100 = (0.779 * imperv) + 0.110
            c500 = (0.654 * imperv) + 0.254
        case 'B':
            cWQE = 0.835 * (imperv ** 1.169)
            c002 = 0.835 * (imperv ** 1.169)
            c005 = 0.857 * (imperv ** 1.088)
            c010 = (0.807 * imperv) + 0.025
            c025 = (0.628 * imperv) + 0.249
            c050 = (0.558 * imperv) + 0.32
            c100 = (0.465 * imperv) + 0.426
            c500 = (0.366 * imperv) + 0.536
        case 'C/D':
            cWQE = 0.834 * (imperv ** 1.122)
            c002 = 0.834 * (imperv ** 1.122)
            c005 = (0.815 * imperv) + 0.035
            c010 = (0.735 * imperv) + 0.132
            c025 = (0.560 * imperv) + 0.319
            c050 = (0.494 * imperv) + 0.393
            c100 = (0.409 * imperv) + 0.484
            c500 = (0.315 * imperv) + 0.588

    return {
        'C WQE': cWQE,
        'C 2-yr': c002,
        'C 5-yr': c005,
        'C 10-yr': c010,
        'C 25-yr': c025,
        'C 50-yr': c050,
        'C 100-yr': c100,
        'C 500-yr': c500,
    }


# -----------------------------------------------
#    LAYOUT FUNCTIONS (other than RENDER)
# -----------------------------------------------

# Remove unruly characters that users might provide in order to make urls
# Convert to lowercase, replace non-alphanumeric with hyphens
def slugify(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')

# Generate links to pages for individual basins
def generate_sidebar_links(basin_dict_list):
    links = [dbc.NavLink('All Basins', href='/', active='exact')]
    for basin in basin_dict_list:
        if True in [x is not None for x in list(basin.values())]:
            links.append(
                dbc.NavLink(
                    f'Basin: {basin['Name']}',
                    href=f'/basin/{slugify(basin['Name'])}',
                    active='exact'
                )
            )
    return links

# Populate sidebar (visible) and url_list using the basin_dict_list, which is
# the list of all basins in the project
@callback(
    Output('dynamic_sidebar', 'children'),
    Input('basin-dict-list', 'data'),
)
def update_sidebar(basin_dict_list):
    if not basin_dict_list:
        pass
    else:
        return generate_sidebar_links(basin_dict_list)


# ----------------------------------------------------------------------------
# --- BASIN STUFF ------------------------------------------------------------
# ----------------------------------------------------------------------------

# Create an empty list for [{basins}] and do any other prelim steps if needed
def init_basin_df():
    return []

# Create a new basin
# NOTE on the state() args below: This uses "Pattern-Matching Callbacks" to
# group all the basin parameters byh type (see the dbc.Input calls in RENDER)
# and then pull them all out here and zip the id/val pairs into a new dict
@callback(
    Output('basin-dict-list', 'data', allow_duplicate=True),
    Input('btn-add-basin', 'n_clicks'),
    State('basin-dict-list', 'data'),
    State({'type': 'basin-input', 'index': ALL}, 'value'),
    State({'type': 'basin-input', 'index': ALL}, 'id'),
    prevent_initial_call=True
)
def create_new_basin(n_clicks, basin_dict_list, values, ids):
    if basin_dict_list is None:
        basin_dict_list = []

    # Zip ids+values as key+val pairs (remember we're using lists of dicts instead of dfs)
    form_data_raw = {node['index']: val for node, val in zip(ids, values)}
    form_data = {k: v for k, v in form_data_raw.items() if k != 'id'}

    # Validation. TODO add robust numerical checks here
    if any(val is None or val == "" for val in form_data.values()):
        raise PreventUpdate

    new_basin = {}
    basin_params = [list(x.values())[0] for x in basin_cols_fld]
    for param in basin_params:
        if param == 'Name':
            new_basin['Name'] = form_data['Name']
        elif param == 'L_i':
            new_basin['L_i'] = form_data['L_i']
        elif param == 'S_i':
            new_basin['S_i'] = form_data['S_i']
        elif param == 'L_t':
            new_basin['L_t'] = form_data['L_t']
        elif param == 'S_t':
            new_basin['S_t'] = form_data['S_t']
        elif param == 'NRCS_K':
            new_basin['NRCS_K'] = form_data['NRCS_K']
        elif param == 'href':
            new_basin['href'] = f'/basin/{slugify(form_data['Name'])}'
        # NOTE overland flow time depends on C5 so it has to wait for areas to be input
        elif param == 'channel_flow_velocity':
            new_basin['channel_flow_velocity'] = form_data['NRCS_K'] * \
                np.sqrt(form_data['S_t'])
        elif param == 't_t':
            new_basin['t_t'] = form_data['L_t'] / (form_data['NRCS_K'] *
                np.sqrt(form_data['S_t']))
        elif param == 'id':
            new_basin['id'] = str(uuid.uuid4())
        else:
            new_basin[param] = None

    basin_dict_list.append(new_basin)
    return basin_dict_list

# DELETE a Basin
@callback(
    Output('basin-dict-list', 'data', allow_duplicate=True),
    Output('areas-dict-list', 'data', allow_duplicate=True),
    Input('btn-remove-basin', 'n_clicks'),
    State('basin-dict-list', 'data'),
    State('basin-grid', 'selectedRows'),
    State('areas-dict-list', 'data'),
    prevent_initial_call=True
)
def delete_basin(
    n_clicks,
    basin_dict_list,
    basin_rows_to_del,
    areas_dict_list
):
    # No selection: do nothing
    if not basin_rows_to_del:
        raise PreventUpdate
    
    # Remove Basin from basin_dict_list
    df_basin = pd.DataFrame(basin_dict_list)
    df_selected = pd.DataFrame(basin_rows_to_del)
    df_updated_basins = df_basin[~df_basin['id'].isin(df_selected['id'])]
    
    if areas_dict_list:
        # Propagate deletion to areas-dict-list
        df_areas = pd.DataFrame(areas_dict_list)
        df_updated_areas = df_areas[~df_areas['basin_id'].isin(df_selected['Name'])]

        return df_updated_basins.to_dict('records'), df_updated_areas.to_dict('records')

    return df_updated_basins.to_dict('records'), None

# ----------
# BASIN editing
# Step ONE: Accept a selected row for editing, then populate that row's 
# existing data into the input form for editing (same form as input)
@callback(
    # One output for each of the form inputs
    Output({'type': 'basin-input', 'index': ALL}, 'value', allow_duplicate=True),
    Output('btn-modify-basin', 'children'),
    Input('btn-modify-basin', 'n_clicks'),
    State('basin-grid', 'selectedRows'),
    State({'type': 'basin-input', 'index': ALL}, 'id'),
    State('btn-modify-basin', 'children'),
    prevent_initial_call=True
)
def populate_basin_edit_data(
    n_clicks, 
    selected_rows, 
    input_ids, 
    button_text,
):
    if not n_clicks or not selected_rows:
        raise PreventUpdate

    if button_text == "Save Basin Update":
        raise PreventUpdate
    
    target_basin = selected_rows[0]
    current_values = []
    for comp_id in input_ids:
        field_key = comp_id['index']
        current_values.append(target_basin.get(field_key, None))

    return current_values, 'Save Basin Updates'


# Step TWO: Write the updated area info back to the areas df
@callback(
    Output('basin-dict-list', 'data', allow_duplicate=True),
    Output('areas-dict-list', 'data', allow_duplicate=True), 
    Output({'type': 'basin-input', 'index': ALL}, 'value'),
    Output('btn-modify-basin', 'children', allow_duplicate=True),
    Input('btn-modify-basin', 'n_clicks'),
    State('basin-dict-list', 'data'),
    State('areas-dict-list', 'data'),                        
    State({'type': 'basin-input', 'index': ALL}, 'id'),
    State({'type': 'basin-input', 'index': ALL}, 'value'),
    State('btn-modify-basin', 'children'),
    prevent_initial_call=True
)
def handle_basin_edit_submission(
    modify_clicks, 
    basin_list, 
    areas_list,
    input_ids, 
    input_values, 
    btn_text
):
    trigger = ctx.triggered_id

    if trigger == 'btn-modify-basin' and btn_text != 'Save Basin Updates':
        raise PreventUpdate
    
    form_data = {parameter['index']: value for parameter, value in zip(input_ids, input_values)}
    target_uuid = form_data.get('id')
    
    validation_values = [v for k, v in form_data.items() if k != 'id']
    if None in validation_values or any(val == "" for val in validation_values):
        raise PreventUpdate

    basin_df = pd.DataFrame(basin_list if basin_list is not None else [])
    updated_areas_list = areas_list

    if not basin_df.empty and target_uuid in basin_df['id'].values:
        idx = basin_df[basin_df['id'] == target_uuid].index[0]
        
        # Extract the old name before rewriting it to check for modifications
        old_name = basin_df.at[idx, 'Name']
        new_name = form_data.get('Name')
        
        # Overwrite standard fields from form
        for key, val in form_data.items():
            if key == 'channel_flow_velocity':
                basin_df.at[idx, 'channel_flow_velocity'] = form_data['NRCS_K'] * np.sqrt(form_data['S_t'])
            elif key == 't_t':
                basin_df.at[idx, 't_t'] = form_data['L_t'] / (form_data['NRCS_K'] * np.sqrt(form_data['S_t']))
            else:
                basin_df.at[idx, key] = val
            
        # Explicitly recalculate href slug because it's not a part of form_data
        basin_df.at[idx, 'href'] = f"/basin/{slugify(new_name)}"
        basin_df.at[idx, 'time_created'] = time.time()

        # If the name changed, migrate all matching child areas to the new name
        if old_name != new_name and areas_list:
            areas_df = pd.DataFrame(areas_list)
            if 'basin_id' in areas_df.columns:
                areas_df.loc[areas_df['basin_id'] == old_name, 'basin_id'] = new_name
                updated_areas_list = areas_df.to_dict('records')

    cleared_inputs = [None] * len(input_ids)

    return (
        basin_df.to_dict('records'),
        updated_areas_list,
        cleared_inputs,
        'Modify Existing Basin' 
    )

# BASIN Ag-Grid display
@callback(
    Output('basin-grid', 'rowData'),
    Input('basin-dict-list', 'data'),
)
def return_basin_ag_grid(basin_dict_list):
    return basin_dict_list if basin_dict_list is not None else []

# Update basin properties when the areas in the basin are updated
@callback(
    Output('basin-dict-list', 'data', allow_duplicate=True),
    Input('areas-dict-list', 'data'),
    Input('precip-array', 'data'),
    State('basin-dict-list', 'data'),
    prevent_initial_call=True
)
def update_basin_props(
        areas_dict_list: list[dict],
        precip_array: dict,
        basin_dict_list: list[dict],
) -> list[dict]:
    # make a df
    if not basin_dict_list:
        raise PreventUpdate

    basin_df = pd.DataFrame(basin_dict_list)
    areas_df = pd.DataFrame(areas_dict_list)


    interval_list = ['WQE', '2-yr', '5-yr', '10-yr', '25-yr', '50-yr', '100-yr', '500-yr']
    interval_list_c = ['C WQE', 'C 2-yr', 'C 5-yr', 'C 10-yr', 'C 25-yr',
            'C 50-yr', 'C 100-yr', 'C 500-yr']
    interval_list_i = ['I WQE', 'I 2-yr', 'I 5-yr', 'I 10-yr', 'I 25-yr',
            'I 50-yr', 'I 100-yr', 'I 500-yr']
    interval_list_q = ['Q WQE', 'Q 2-yr', 'Q 5-yr', 'Q 10-yr', 'Q 25-yr',
            'Q 50-yr', 'Q 100-yr', 'Q 500-yr']

    # Calculate area- and precip-dependent properties, provided there are areas
    if len(areas_df) > 0:
        for index, basin in basin_df.iterrows():

            # Sum the areas
            area_sum = areas_df.loc[areas_df['basin_id']==basin['Name'], 'Area'].sum()
            basin_df.at[index, 'Area'] = area_sum

            # List the soil types
            soil_list = sorted(list(set([areas_df.loc[areas_df['basin_id']==basin['Name'], 'Soil Type']][0])))
            basin_df.at[index, 'Soils'] = soil_list

            # Return-period values
            for c in interval_list_c:
                # Weighted average of c-values (not typical but used in MHFD sheet - thanks Eric at CAGE)
                if area_sum > 0.00001:
                    weighted_avg_c = (areas_df.loc[areas_df['basin_id'] == basin['Name'], c] *
                        areas_df.loc[areas_df['basin_id'] == basin['Name'], 'Area']).sum() / area_sum
                else:
                    weighted_avg_c = 0

                basin_df.at[index, c] = weighted_avg_c

            # Use basin_df here, as the c value is updated above and 'basin' from the loop
            # control might be a copy. TODO try this conditional with 'basin' as control vs basin_df
            if basin_df.at[index, 'C 5-yr'] is not None:
                basin_df.at[index, 't_i'] = 0.395*(1.1-basin_df.at[index, 'C 5-yr'])*\
                    np.sqrt(basin_df.at[index, 'L_i']) / basin_df.at[index, 'S_i']**0.33
                basin_df.at[index, 't_c_basin'] = basin_df.at[index, 't_i'] + basin_df.at[index, 't_t']

                for i in interval_list:
                    intensity_name = f'I {i}'
                    q_name = f'Q {i}'
                    c_name = f'C {i}'
                    depth = precip_array[i] if precip_array[i] else 0
                    # Rainfall Intensity depends on P1 T_d, assumed equal to t_c in this implementation of the RM
                    intensity = 28.5 * depth / (10. + basin_df.at[index, 't_c_basin'])**0.786
                    basin_df.at[index, intensity_name] = intensity
                    basin_df.at[index, q_name] = basin_df.at[index, c_name] * intensity * area_sum

    basin_dict_list_updated = basin_df.to_dict('records')
    return basin_dict_list_updated



# ----------------------------------------------------------------------------
# --- AREAS Stuff ------------------------------------------------------------
# ----------------------------------------------------------------------------
# Note: the areas shown for a basin are a slice of the overall areas list
# of dicts. 

# Create AREA and add to [{areas}]
@callback(
    Output('areas-dict-list', 'data'),
    Input('add-area', 'n_clicks'),
    State('areas-dict-list', 'data'),
    State('active-basin', 'data'),
    State('area-ac', 'value'),
    State('soil-select', 'value'),
    State('imperv-select', 'value'),
)
def add_area(
        n_clicks: int,
        areas_dict_list: list[dict],
        active_basin: dict,
        area_ac: float,
        soil: str,
        imperv: float
):

    if n_clicks == 0:
        raise PreventUpdate

    if None in [area_ac, soil, imperv]:
        raise PreventUpdate

    if areas_dict_list is None or areas_dict_list == []:
        area_col_list = [list(x.values())[0] for x in area_cols_fld]
        areas_dict_df = pd.DataFrame(columns=area_col_list)
    else:
        areas_dict_df = pd.DataFrame(areas_dict_list)

    new_row_pt1 = {
        'Area': area_ac,
        'Soil Type': soil,
        '% Impervious': imperv,
    }
    new_row_pt2 = get_c_values(soil, imperv)
    new_row_pt3 = {
        'id': str(uuid.uuid4()),
        'time_created': time.time(),
        'basin_id': active_basin['Name'] if active_basin else 'Unknown',
    }
    new_row = new_row_pt1 | new_row_pt2 | new_row_pt3

    # 3.  the record cleanly without dummy rows
    areas_dict_df.loc[len(areas_dict_df)] = new_row

    return areas_dict_df.to_dict('records')


# DELETE AREA
# Note this needs to actually remove the row from the table
@callback(
    # Updating the table should trigger the render callback, so no need to call it here
    Output('areas-dict-list', 'data', allow_duplicate=True),
    Input('btn-remove-selected-area', 'n_clicks'),
    State('areas-dict-list', 'data'),
    State('area-grid', 'selectedRows'),
    prevent_initial_call=True
)
def remove_area(remove_clicks, areas_dict_list, selected_rows):
    if not selected_rows:
        raise PreventUpdate

    df_areas = pd.DataFrame(areas_dict_list)
    df_selected = pd.DataFrame(selected_rows)
    df_updated = df_areas[~df_areas['id'].isin(df_selected['id'])]

    return df_updated.to_dict('records')


# ----------
# AREA editing
# Step ONE: Accept a selected row for editing, then populate that row's 
# existing data into the input form for editing (same form as input)
# TODO: branch and try a version where the text on the input button isn't the trigger,
# but instead we use a dcc.Store component 'area-edit-mode' 
@callback(
    Output('area-ac', 'value', allow_duplicate=True),
    Output('soil-select', 'value', allow_duplicate=True),
    Output('imperv-select', 'value', allow_duplicate=True),
    Output('btn-modify-area', 'children'),
    Output('editing-area-id', 'data'),
    Input('btn-modify-area', 'n_clicks'),
    State('area-grid', 'selectedRows'),
    State('btn-modify-area', 'children'),
    prevent_initial_call=True
)
def populate_area_edit_data(n_clicks, selected_rows, button_text):
    if not n_clicks or not selected_rows:
        raise PreventUpdate

    # If the user clicks button while it says 'Save Area Updates', this function shouldn't trigger 
    # (but the write-back function SHOULD trigger) - do nothing here 
    if button_text == 'Save Area Updates':
        raise PreventUpdate

    # Read the chosen row attributes
    target_row = selected_rows[0]

    return (
        target_row.get('Area'),
        target_row.get('Soil Type'),
        target_row.get('% Impervious'),
        'Save Area Updates',            # Toggles button text
        target_row.get('id')            # Passes row UUID down to state storage
    )

# Step TWO: Write the updated area info back to the areas df
@callback(
    Output('areas-dict-list', 'data'),
    Output('area-ac', 'value'),
    Output('soil-select', 'value'),
    Output('imperv-select', 'value'),
    Output('btn-modify-area', 'children', allow_duplicate=True),
    Input('btn-modify-area', 'n_clicks'),
    State('areas-dict-list', 'data'),
    State('active-basin', 'data'),
    State('area-ac', 'value'),
    State('soil-select', 'value'),
    State('imperv-select', 'value'),
    State('editing-area-id', 'data'),
    State('btn-modify-area', 'children'),
    prevent_initial_call=True
)
def handle_area_edit_submission(
        # add_clicks,
        modify_clicks,
        areas_dict_list,
        active_basin,
        area_ac,
        soil,
        imperv,
        editing_id,
        btn_text
):
    trigger = ctx.triggered_id

    # Defensive Guard checks
    if None in [area_ac, soil, imperv]:
        raise PreventUpdate

    if trigger == 'btn-modify-area' and btn_text != 'Save Area Updates':
        raise PreventUpdate

    # Instantiate or load historical DataFrame
    if areas_dict_list is None:
        area_col_list = [list(x.values())[0] for x in area_cols_fld]
        areas_dict_df = pd.DataFrame(columns=area_col_list)
    else:
        areas_dict_df = pd.DataFrame(areas_dict_list)

    # Compute updated hydrologic constants
    c_values = get_c_values(soil, imperv)

    if trigger == 'btn-modify-area' and editing_id is not None:
        if editing_id in areas_dict_df['id'].values:
            idx = areas_dict_df[areas_dict_df['id'] == editing_id].index[0]

            areas_dict_df.at[idx, 'Area'] = area_ac
            areas_dict_df.at[idx, 'Soil Type'] = soil
            areas_dict_df.at[idx, '% Impervious'] = imperv

            for c_key, c_val in c_values.items():
                areas_dict_df.at[idx, c_key] = c_val

            areas_dict_df.at[idx, 'time_created'] = time.time() # bump sort timestamp

    # Return updated list, and reset the form UI parameters safely
    return (
        areas_dict_df.to_dict('records'),
        None,                        # Resets area input box to blank
        None,                        # Resets soil selection dropdown
        None,                        # Resets imperv input box to blank
        'Modify Existing Area'       # Flips text back to baseline state
    )


# UPDATE AREA AG-GRID ON CHANGE
@callback(
    Output('area-grid', 'rowData'),
    Input('areas-dict-list', 'data'),
    State('active-basin', 'data'),
    prevent_initial_call=True
)
def update_area_grid_on_df_change(
        areas_dict_list,
        active_basin: dict,
):
    if not areas_dict_list or not active_basin:
        return []

    df_areas = pd.DataFrame(areas_dict_list)
    df_sliced = df_areas[df_areas['basin_id'] == active_basin['Name']]
    return df_sliced.to_dict('records')


# ----------------------------------------------------------------------------
# --- PRECIP STUFF -----------------------------------------------------------
# ----------------------------------------------------------------------------
# Note we are using a flexible callback signature to group the precip cells
# Updates to precip trigger recomputing the basin table
@callback(
    Output('precip-array', 'data'),
    Output({'type': 'matrix-cell', 'index': ALL}, 'invalid'),  # Dynamically turns borders red
    Output('validation-warning', 'children'),
    Input({'type': 'matrix-cell', 'index': ALL}, 'value'),
    State({'type': 'matrix-cell', 'index': ALL}, 'id'),
    prevent_initial_call=True
)
def precip_input_validated(values, ids):
    updated_dict = {}
    invalid_states = []
    has_error = False

    # Dash passes the contextual inputs_list so we know exactly which input is which
    for node, val in zip(dash.callback_context.inputs_list[0], values):
        col_name = node['id']['index']

        # 1. Handle empty cells (Don't trigger an error, just record as None)
        if val is None or str(val).strip() == "":
            updated_dict[col_name] = None
            invalid_states.append(False)
            continue

        # 2. Handle numeric validation
        try:
            float_val = float(val)
            if 0.0 <= float_val <= 5.0:
                # Valid: Add to dictionary, mark input as NOT invalid
                updated_dict[col_name] = float_val
                invalid_states.append(False)
            else:
                # Invalid Range: Exclude from dictionary, mark input as invalid (True)
                updated_dict[col_name] = None
                invalid_states.append(True)
                has_error = True
        except ValueError:
            # Catch non-numeric garbage data
            updated_dict[col_name] = None
            invalid_states.append(True)
            has_error = True

    # Generate the warning message if any errors were found
    warning_message = "Warning: Values outside the 0-5 range have been ignored." if has_error else ""

    # Return 1) The clean data, 2) The list of red borders, 3) The warning text
    return updated_dict, invalid_states, warning_message


# Helper to view the Precip dcc.Store in dev
@callback(
    Output('store-output', 'children'),
    Input('precip-array', 'data')
)
def display_store(data):
    return json.dumps(data, indent=2) if data else "Store is currently empty."


# --- --- ---

# 1. AREAS STATE CONTROLLER: Watches the URL and updates the active-basin Store
@callback(
    Output('active-basin', 'data'),
    Input('url', 'pathname'),
    Input('basin-dict-list', 'data'), 
    State('active-basin', 'data'),  # Inspect the current state before overwriting
)
def determine_active_basin(pathname, basin_dict_list, current_active):
    if not pathname or not basin_dict_list:
        return None

    # 1. Try to match directly by the active route path
    for basin in basin_dict_list:
        if basin.get('href') == pathname:
            return basin

    # 2. Fallback: If mid-rename, look up the basin by its persistent immutable UUID
    if current_active and pathname != '/':
        for basin in basin_dict_list:
            if basin.get('id') == current_active.get('id'):
                return basin

    return None

# 2. UI RENDERER: Watches the active-basin and URL, then pushes the HTML layout
@callback(
    Output('page-content', 'children'),
    Input('url', 'pathname'),
    Input('active-basin', 'data'),  # Fires right after the controller sets the data
    State('areas-dict-list', 'data'),
    State('precip-array', 'data'),
    State('basin-dict-list', 'data')
)
def render_page_layout(pathname, active_basin, areas_dict_list, precip_array, basin_dict_list):
    if not pathname:
        raise PreventUpdate

    # Calculate valid URLs
    basin_urls = [b['href'] for b in basin_dict_list if b.get('href')] if basin_dict_list else []

    # Display Homepage
    if pathname == '/':
        print('rendering main')
        return html.Div([
            html.H4("Enter P1 values from NOAA or other precip. source", className="mt-4 mb-3"),
            html.Table(
                [
                    html.Thead(html.Tr(
                        [html.Th(col, style={'textAlign': 'center', 'padding': '8px'}) for col in precip_cols])),
                    html.Tbody(html.Tr([
                        html.Td(
                            dbc.Input(
                                id={'type': 'matrix-cell', 'index': col},
                                placeholder='-',
                                value=precip_array[col] if precip_array is not None else '',
                                style={'textAlign': 'center'}
                            ),
                            style={'padding': '4px'}
                        ) for col in precip_cols
                    ]))
                ],
                style={'width': '100%', 'borderCollapse': 'collapse', 'marginBottom': '20px'}
            ),
            html.Div(id='validation-warning',
                     style={'color': '#dc3545', 'minHeight': '24px', 'fontWeight': 'bold', 'marginBottom': '15px'}),
            html.P('Enter basin parameters'),
            dbc.Col([
                html.Div(
                    dbc.Input(id={'type': 'basin-input', 'index': 'id'}, type='text'),
                    style={'display': 'none'}
                ),
                dbc.Row([dbc.Col(html.Div('Basin Name'), width=4), dbc.Col(
                    dbc.Input(id={'type': 'basin-input', 'index': 'Name'}, type='text', placeholder='Basin Name'),
                    width=3)]),
                dbc.Row([dbc.Col(html.Div(['Overland Flow Length, L', html.Sub('i'), ' (ft)']), width=4),
                         dbc.Col(dbc.Input(id={'type': 'basin-input', 'index': 'L_i'}, type='number', min=0.01),
                                 width=3)]),
                dbc.Row([dbc.Col(html.Div(['Overland Flow Slope, S', html.Sub('i'), ' (ft/ft)']), width=4),
                         dbc.Col(dbc.Input(id={'type': 'basin-input', 'index': 'S_i'}, type='number', min=0.0001),
                                 width=3)]),
                dbc.Row([dbc.Col(html.Div(['Channelized Flow Length, L', html.Sub('t'), ' (ft)']), width=4),
                         dbc.Col(dbc.Input(id={'type': 'basin-input', 'index': 'L_t'}, type='number', min=0.01),
                                 width=3)]),
                dbc.Row([dbc.Col(html.Div(['Channelized Flow Slope, S', html.Sub('t'), ' (ft/ft)']), width=4),
                         dbc.Col(dbc.Input(id={'type': 'basin-input', 'index': 'S_t'}, type='number', min=0.0001),
                                 width=3)]),
                dbc.Row([dbc.Col(html.Div(['NRCS Conveyance Factor (K)']), width=4),
                         dbc.Col(dbc.Input(id={'type': 'basin-input', 'index': 'NRCS_K'}, type='number', min=0.01),
                                 width=3)]),
            ]),
            dbc.Row([
                dbc.Col(dbc.Button('Add Basin', id='btn-add-basin', n_clicks=0, color='primary'), width='auto'),
                dbc.Col(dbc.Button('Modify Selected Basin', id='btn-modify-basin', n_clicks=0, color='secondary'), width='auto'),
                dbc.Col(dbc.Button('Remove Selected Basin', id='btn-remove-basin', color='danger'), width='auto'),
            ], className='g-2 my-3'),
            dag.AgGrid(
                id='basin-grid',
                columnDefs=basin_cols_fld,
                rowData=basin_dict_list if basin_dict_list is not None else [],
                dashGridOptions={'rowSelection': {'mode': 'singleRow'}}
            )
        ])

    # Check if the URL matches a known basin, OR if we are currently mid-rename sync loop
    matched_basin = None
    if basin_dict_list and active_basin:
        for b in basin_dict_list:
            # Match directly by href OR match by UUID if we are in the middle of renaming it
            if b.get('href') == pathname or b.get('id') == active_basin.get('id'):
                matched_basin = b
                break

    # Display Basin Page safely
    if matched_basin:
        print('rendering sub-page')

        filtered_area_rows = []
        if areas_dict_list:
            df_areas = pd.DataFrame(areas_dict_list)
            df_slice = df_areas[df_areas['basin_id'] == matched_basin['Name']]
            filtered_area_rows = df_slice.to_dict('records')

        return html.Div([
            dcc.Store(id='editing-area-id', data=None),

            dcc.Markdown(f'### Basin {matched_basin["Name"]}: Add areas'),
            dbc.Row([dbc.Col(html.Div('Area (acres)'), width=2),
                     dbc.Col(dbc.Input(id='area-ac', type='number', min=0.0001), width=3)]),
            dbc.Row([dbc.Col(html.Div('NRCS Soil Group'), width=2), dbc.Col(dbc.Select(id='soil-select', options=[
                {'label': 'A', 'value': 'A'}, {'label': 'B', 'value': 'B'}, {'label': 'C/D', 'value': 'C/D'}]),
                                                                            width=3)]),
            dbc.Row([dbc.Col(html.Div('% Impervious'), width=2),
                     dbc.Col(dbc.Input(id='imperv-select', type='number', min=0.0001), width=3)]),
            
            dbc.Row([
                dbc.Col(dbc.Button('Add Area', id='add-area', n_clicks=0, color='primary'), width='auto'),
                dbc.Col(dbc.Button('Modify Existing Area', id='btn-modify-area', n_clicks=0, color='secondary'), width='auto'),
                dbc.Col(dbc.Button('Remove Selected Row', id='btn-remove-selected-area', color='danger'), width='auto'),
            ], className='g-2 my-3'),
            
            dag.AgGrid(
                id='area-grid',
                columnDefs=area_cols_fld,
                rowData=filtered_area_rows,
                dashGridOptions={'rowSelection': {'mode': 'singleRow'}}
            ),
        ])

    # Default 404 message
    return html.Div([
        html.H1('404: Not found', className='text-danger'),
        html.Hr(),
        html.P(f'The pathname {pathname} was not recognized...'),
    ], className='p-3 bg-light rounded-3')


# 3. ROUTE SYNC CONTROLLER: Automatically redirects the browser 
# if an active basin's name (and href) gets modified.
@callback(
    Output('url', 'pathname', allow_duplicate=True),
    Input('basin-dict-list', 'data'),
    State('active-basin', 'data'),
    State('url', 'pathname'),
    prevent_initial_call=True
)
def sync_url_on_basin_rename(basin_dict_list, active_basin, current_pathname):
    if not basin_dict_list or not active_basin:
        raise PreventUpdate

    # Look up the modified basin using its immutable UUID string
    for basin in basin_dict_list:
        if basin.get('id') == active_basin.get('id'):
            new_href = basin.get('href')
            # If the database href changed relative to the current route, redirect the web browser!
            if new_href and new_href != current_pathname and current_pathname != '/':
                return new_href
                
    raise PreventUpdate


# -----------------------------------------------
# Layout
# -----------------------------------------------

app = dash.Dash(__name__,
suppress_callback_exceptions=True)
# external_stylesheets=[dbc.themes.BOOTSTRAP],

SIDEBAR_STYLE = {
    'position': 'fixed',
    'top': 0,
    'left': 0,
    'bottom': 0,
    'width': '16rem',
    'padding': '2rem 1rem',
    'background-color': '#f8f9fa',
}

# the styles for the main content position it to the right of the sidebar and
# add some padding.
CONTENT_STYLE = {
    'margin-left': '10rem',
    'margin-right': '2rem',
    'padding': '2rem 1rem',
}

sidebar = html.Div(
    [
        html.H2('Basins', className='display-4'),
        html.Hr(),
        html.P('Click a basin name to view its parameters', className='lead'),
        dbc.Nav(
            id='dynamic_sidebar',
            vertical=True,
            pills=True,
        ),
    ],
    style=SIDEBAR_STYLE,
)

content = html.Div([
    html.Div(id='page-content', style=CONTENT_STYLE),
],
    style=CONTENT_STYLE
)
app.layout = html.Div([
    # Main dcc.Stores
    dcc.Store(id='basin-dict-list', data=None, storage_type='session'),
    dcc.Store(id='areas-dict-list', data=None, storage_type='session'),
    dcc.Store(id='precip-array', data=None, storage_type='session'),
    dcc.Store(id='active-basin', data=None, storage_type='session'),

    # dcc.Location(id='url'),
    dcc.Location(id='url', refresh=False),
    sidebar,
    content
])

if __name__ == '__main__':
    app.run(port=8050)
    # app.run(debug=True)
    # app.run(debug=True, use_reloader=False)