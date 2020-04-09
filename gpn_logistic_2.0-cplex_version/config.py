import os

all_configuration = {
    'prod': {
        'time_limit': 900,
        'launch_after_calc_validation': True,
        'period_flow_balance_coef': 1.0,
        'max_truck_to_asu': 2,
    },
    'preprod': {
        'time_limit': 50,
        'launch_after_calc_validation': False,
        'period_flow_balance_coef': 0.9,
        'max_truck_to_asu': 1,
    },
    'test': {
        'time_limit': 50,
        'launch_after_calc_validation': False,
        'period_flow_balance_coef': 0.9,
        'max_truck_to_asu': 1,
    },
    'default': {
        'time_limit': 50,
        'launch_after_calc_validation': False,
        'period_flow_balance_coef': 0.9,
        'max_truck_to_asu': 1,
    }
}

configuration = all_configuration[
    os.environ.get(
        'NAMESPACE',
        'default'
)]

time_limit = os.environ.get('GPN_LOGISTIC_TIME_LIMIT')
if time_limit:
    configuration['time_limit'] = int(time_limit)
