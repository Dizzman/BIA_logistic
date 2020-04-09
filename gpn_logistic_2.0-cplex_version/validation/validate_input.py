"""Центральный модуль запуска валидации данных. Осуществляет последовательную
проверку данных на корректность.
"""

from .components.prevalidate_reservoir_overflow import validate_reservoir_overflow


def validate():
    validate_reservoir_overflow()
