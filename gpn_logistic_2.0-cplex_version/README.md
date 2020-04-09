gpn_logistic_2.0
================

Расчётный модуль проекта, который реализует построение расписания доставки топлива по переданным от интеграционного модуля данным.

Содержание
----------

- data_reader - модуль считывания и конвертации входных данных в объекты модели, а также преобразование данных о временных окнах работы АЗС в формат, пригодный для расчёта.

- input/scenatio_2 - каталог с данными, попадающие в расчёт при запуске модели. Содержит все справочники и параметры расчёта.

- integral_planning - модуль расчета объема поставки топлива на АЗС с учетом дальнего горизонта планирования

- detailed_planning - модуль расчета рейсов

- logs - каталог для записи промежуточных lp моделей перепривязок АЗС и НБ

- models_connector - модуль преобразования выходных данных из модели потоков (integral_planning), в модуль детального планирования (detailed_planning)

- output - Папка с файлами, содержит все таблицы выходных данных, передаваемых обратно в 1С и также вспомогательных таблиц и рисунков, которые помогают визуализировать расчеты модели

- output_writer - модуль записи решения в виде таблиц для передачи в 1с и интеграции

- ploter - модуль построения диаграмм ганта расписания движения и графика проведения разлиных работ БВ

- schedule_writer - Блок записи расписания в виде таблиц для внутренней аналитики качества расчета

- test_pack - набор тестов, для проверки краевых случаев работы модели

- timetable_calculator - модуль расчета расписания бензовозов

- validation - модуль валидации входных данных на переполнение резервуаров и модуль валидации результирующего решения

- main_script.py - скрипт запуска модуля расчета

- rest - каталог с реализацией web API для взаимодействия с интеграционным модулем через http/https запросы

Способ получения артефактов
---------------------------
Gitlab CI, запускаемый в ручном режиме или через сценарии исполнения при добавлении свежих исправлений, реализуемый через описание сборки в специальном
файле .gitlab-ci.yml. 


Результирующие артефакты
------------------------
Результатом работы стадий Gitlab CI является docker-образ с расчётным модулем и зависимостями, реализующими функциональность проекта при развёртывании в openshift среде


Ветки
-----
cplex_version - версия для разработки и локального тестирования

cplex_test - версия для тестирования, разворачиваемая в окружение gpntest

cplex_preprod - версия для интеграционного тестирования с контекстом, близким к production, разворачиваемая в окружение gpnpreprod

cplex_prod - версия для production, разворачиваемая в окружение gpnprod