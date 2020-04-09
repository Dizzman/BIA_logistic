from itertools import permutations, product, starmap


def extend_function(list1, list2):
    result = list(list1)
    result.extend(list2)

    return result


# TODO filter for distance
def route_permutation(route: list):

    return list(permutations(route))


'''Load combinations:
    - Generation of all sequences of section sequences
    - Route permutations'''


def load_permutations(route: list, asu_tanks: dict):  # routes = [[asu1, asu2], [], ...]; asu_tanks = {asu1: [(asu1, n), (asu1, n)], ...}

    combinations = []  # Combinations of loads [[(asu1, n), (asu2, n)], ...]
    set_of_permutations = {}  # Permutations of one asu {asu1: [(asu1, n2), (asu1, n1)], [(asu1, n2), (asu1, n1)], ...}

    '''Permutations generation for every asu'''
    for asu in asu_tanks:
        set_of_permutations[asu] = list(permutations(asu_tanks[asu]))

    '''Route load possible sequences generation'''
    routes_combinations = route_permutation(route)
    for route_com in routes_combinations:
        count = 0
        combination = []

        for asu in route_com:
            if count == 0:
                combination = set_of_permutations[asu]
                count += 1
                # '''The route consist of one asu'''
                # if len(route_com) == 1:
                #     combinations.extend(combination)
                #     return combinations
            else:
                '''Add permutations for current sequences of load'''
                combination_new = list(product(combination, set_of_permutations[asu]))
                combination = list(starmap(extend_function, combination_new))

                count += 1
        combinations.extend(combination)

    return combinations
