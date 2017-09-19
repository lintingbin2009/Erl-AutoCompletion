import os, fnmatch, re, threading, sublime, json, sqlite3, shutil, time
from .settings import get_settings_param, GLOBAL_SET

CREATE_LIBS_SQL = '''
create table if not exists `libs` (
  `id` integer PRIMARY KEY autoincrement,
  `mod_name` varchar(128) not null,
  `fun_name` varchar(128) not null,
  `param_len` tinyint(2) not null,
  `file_path` varchar(256) not null,
  `row_num` int unsigned not null,
  `completion` varchar(256) not null
); 
'''
INSERT_LIBS_SQL = '''
replace into libs(mod_name, fun_name, param_len, file_path, row_num, completion) values 
(?, ?, ?, ?, ?, ?);
'''

QUERY_COMPLETION = '''
select fun_name, param_len, completion from libs where mod_name = ?;
'''

QUERY_ALL_MOD = '''
select distinct mod_name from libs;
'''

QUERY_POSITION = '''
select fun_name, param_len, file_path, row_num from libs where mod_name = ? and fun_name = ?
'''

class DataCache:
    def __init__(self, dir = '', data_type = '', cache_dir = ''):
        self.dir = dir
        self.data_type = data_type
        self.cache_dir = cache_dir
        self.re_dict = GLOBAL_SET['compiled_re']
        self.version = get_settings_param('sublime_erlang_version', '0.0.0')
        self.is_ready = False
        if cache_dir != '':
            self.__init_db()

    def __init_db(self):
        db_path = self.__get_filepath('completion')
        try:
            self.db_con = sqlite3.connect(db_path, check_same_thread = False)
            self.db_cur = self.db_con.cursor()
            self.db_cur.execute(CREATE_LIBS_SQL)
        except Exception as e:
            self.db_con.close()
            print('Exception', e)
            shutil.rmtree(self.cache_dir)
            print('Remove dir {}.'.format(self.cache_dir))
            db_path = self.__get_filepath('completion')
            self.db_con = sqlite3.connect(db_path, check_same_thread = False)
            self.db_cur = self.db_con.cursor()
            self.db_cur.execute(CREATE_LIBS_SQL)

    def query_mod_fun(self, module):
        if not self.is_ready:
            return []

        self.db_cur.execute(QUERY_COMPLETION, (module, ))
        query_data = self.db_cur.fetchall()

        completion_data = []
        for (fun_name, param_len, completion) in query_data:
            completion_data.append(['{}/{}\tMethod'.format(fun_name, param_len), completion])

        return completion_data

    def query_all_mod(self):
        if not self.is_ready:
            return []
        
        self.db_cur.execute(QUERY_ALL_MOD)
        query_data = self.db_cur.fetchall()

        completion_data = []
        for (mod_name, ) in query_data:
            completion_data.append(['{}\tModule'.format(mod_name), mod_name])

        return completion_data

    def query_fun_position(self, module, function):
        if not self.is_ready:
            return []

        self.db_cur.execute(QUERY_POSITION, (module, function))
        query_data = self.db_cur.fetchall()

        completion_data = []
        for (fun_name, param_len, file_path, row_num) in query_data:
            completion_data.append(('{}/{}'.format(fun_name, param_len), file_path, row_num))

        return completion_data

    def build_module_dict(self, filepath):
        with open(filepath, encoding = 'UTF-8', errors='ignore') as fd:
            content = fd.read()
            code = re.sub(self.re_dict['comment'], '\n', content)

            export_fun = {}
            for export_match in self.re_dict['export'].finditer(code):
                for funname_match in self.re_dict['funname'].finditer(export_match.group()):
                    [name, cnt] = funname_match.group().split('/')
                    export_fun[(name, int(cnt))] = None
            module = self.get_module_from_path(filepath)

            row_num = 1
            for line in code.split('\n'):
                funhead = self.re_dict['funline'].search(line)
                if funhead is not None: 
                    fun_name = funhead.group(1)
                    param_str = funhead.group(2)
                    param_list = self.format_param(param_str)
                    param_len = len(param_list)
                    if (fun_name, param_len) in export_fun:
                        del(export_fun[(fun_name, param_len)])
                        completion = self.__tran2compeletion(fun_name, param_list, param_len)
                        self.db_cur.execute(INSERT_LIBS_SQL, (module, fun_name, param_len, filepath, row_num, completion))
                row_num += 1

    def get_module_from_path(self, filepath):
        (path, filename) = os.path.split(filepath)
        (module, extension) = os.path.splitext(filename)

        return module

    def format_param(self, param_str):
        param_str = re.sub(self.re_dict['special_param'], 'Param', param_str)
        param_str = re.sub(self.re_dict['='], '', param_str)

        if param_str == '' or re.match('\s+', param_str):
            return []
        else:
            return re.split(',\s*', param_str)

    def __tran2compeletion(self, funname, params, len):
        param_list = ['${{{0}:{1}}}'.format(i + 1, params[i]) for i in range(len)]
        param_str = ', '.join(param_list)
        completion = '{0}({1})${2}'.format(funname, param_str, len + 1)
        return completion

    def __get_filepath(self, filename):
        if not os.path.exists(self.cache_dir): 
            os.makedirs(self.cache_dir)
        real_filename = '{0}_{1}'.format(self.data_type, filename)
        filepath = os.path.join(self.cache_dir, real_filename)
        return filepath

    def __dump_json(self, filename, data):
        filepath = self.__get_filepath(filename)
        with open(filepath, 'w') as fd:
            fd.write(json.dumps(data))

    def build_data(self):
        all_filepath = []
        for dir in self.dir:
            for root, dirs, files in os.walk(dir):
                for file in fnmatch.filter(files, '*.erl'):
                    all_filepath.append(os.path.join(root, file))

        for filepath in all_filepath:
            self.build_module_dict(filepath)
        
        self.db_con.commit()

    def build_data_async(self):
        this = self
        class BuildDataAsync(threading.Thread):
            def run(self):
                start_time = time.time()
                print("start", start_time)
                this.build_data()
                print("end", time.time() - start_time)
                this.is_ready = True
                
        BuildDataAsync().start()