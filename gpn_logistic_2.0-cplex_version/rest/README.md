================
API gpn_logistic

/upload_input: принимает mulipart post запрос с набором файлов, кладёт их в UPLOAD_FOLDER (/tmp/gpn_logistic_2.0/input/scenario_2/)

/upload_list: возвращает списко файлов в каталоге INPUT_FOLDER 

/calculate: начинает расчёт (в отдельном процессе), если расчёт в данный момент не шёл.

/current_log: возвращает текущий stdout/stderr расчётного процесса

/status: возвращает статус рачёта: {'status': STATUS}, где STATUS - один из 'not started', 'calculating', 'finished successfully', 'error'
		
/kill: завершает текущий процесс

/output_list: возрващает список файлов в каталоге OUTPUT_FOLDER {
    { 'files': { 'file1.xslx': { 'size':12356 }, 'file2.xslx': { 'size': 111 } } }

/output/filename: возвращает файл запроса
