#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef M7A_GUI_MODE
#define M7A_GUI_MODE 1
#endif

#define M7A_PATH_BUF 4096

static int resolve_executable_path(char *out, size_t out_size) {
    uint32_t size = 0;
    _NSGetExecutablePath(NULL, &size);
    if (size == 0) {
        return -1;
    }

    char *raw = (char *)malloc((size_t)size + 1);
    if (!raw) {
        return -1;
    }

    if (_NSGetExecutablePath(raw, &size) != 0) {
        free(raw);
        return -1;
    }
    raw[size] = '\0';

    char resolved[PATH_MAX];
    if (!realpath(raw, resolved)) {
        free(raw);
        return -1;
    }
    free(raw);

    if (strlen(resolved) >= out_size) {
        return -1;
    }
    snprintf(out, out_size, "%s", resolved);
    return 0;
}

static int strip_path_components(const char *path, int levels, char *out, size_t out_size) {
    if (!path || !out || out_size == 0) {
        return -1;
    }
    if (strlen(path) >= out_size) {
        return -1;
    }
    snprintf(out, out_size, "%s", path);

    for (int i = 0; i < levels; i++) {
        size_t len = strlen(out);
        while (len > 1 && out[len - 1] == '/') {
            out[--len] = '\0';
        }
        char *slash = strrchr(out, '/');
        if (!slash) {
            return -1;
        }
        if (slash == out) {
            out[1] = '\0';
        } else {
            *slash = '\0';
        }
    }
    return 0;
}

static int mkdir_p(const char *path, mode_t mode) {
    char tmp[M7A_PATH_BUF];
    size_t len = strlen(path);
    if (len == 0 || len >= sizeof(tmp)) {
        return -1;
    }
    snprintf(tmp, sizeof(tmp), "%s", path);
    if (tmp[len - 1] == '/' && len > 1) {
        tmp[len - 1] = '\0';
    }

    for (char *p = tmp + 1; *p; p++) {
        if (*p == '/') {
            *p = '\0';
            if (mkdir(tmp, mode) != 0 && errno != EEXIST) {
                return -1;
            }
            *p = '/';
        }
    }
    if (mkdir(tmp, mode) != 0 && errno != EEXIST) {
        return -1;
    }
    return 0;
}

static void ensure_system_path(void) {
    const char *cur = getenv("PATH");
    const char *fallback = "/usr/bin:/bin:/usr/sbin:/sbin";
    if (!cur || cur[0] == '\0') {
        setenv("PATH", fallback, 1);
        return;
    }
    if (strstr(cur, "/usr/bin") != NULL && strstr(cur, "/bin") != NULL) {
        return;
    }
    size_t needed = strlen(cur) + strlen(fallback) + 2;
    char *updated = (char *)malloc(needed);
    if (!updated) {
        return;
    }
    snprintf(updated, needed, "%s:%s", cur, fallback);
    setenv("PATH", updated, 1);
    free(updated);
}

static void redirect_gui_stdio_if_needed(void) {
#if M7A_GUI_MODE
    if (isatty(STDOUT_FILENO) && isatty(STDERR_FILENO)) {
        return;
    }
    char data_dir[M7A_PATH_BUF];
    const char *env_data = getenv("M7A_DATA_DIR");
    if (env_data && env_data[0] != '\0') {
        snprintf(data_dir, sizeof(data_dir), "%s", env_data);
    } else {
        const char *home = getenv("HOME");
        if (!home || home[0] == '\0') {
            return;
        }
        snprintf(data_dir, sizeof(data_dir), "%s/Library/Application Support/March7thAssistant", home);
    }

    char logs_dir[M7A_PATH_BUF];
    char log_file[M7A_PATH_BUF];
    if (snprintf(logs_dir, sizeof(logs_dir), "%s/logs", data_dir) >= (int)sizeof(logs_dir)) {
        return;
    }
    if (snprintf(log_file, sizeof(log_file), "%s/gui_launch.log", logs_dir) >= (int)sizeof(log_file)) {
        return;
    }
    if (mkdir_p(logs_dir, 0755) != 0) {
        return;
    }

    int fd = open(log_file, O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd < 0) {
        return;
    }
    if (!isatty(STDOUT_FILENO)) {
        dup2(fd, STDOUT_FILENO);
    }
    if (!isatty(STDERR_FILENO)) {
        dup2(fd, STDERR_FILENO);
    }
    if (fd > STDERR_FILENO) {
        close(fd);
    }
#endif
}

static int inject_bundle_paths(const char *site_packages_dir, const char *app_dir) {
    PyObject *builtins = PyEval_GetBuiltins();
    PyObject *globals = PyDict_New();
    if (!globals) {
        return -1;
    }
    if (builtins && PyDict_SetItemString(globals, "__builtins__", builtins) != 0) {
        Py_DECREF(globals);
        return -1;
    }

    PyObject *py_sp = PyUnicode_DecodeFSDefault(site_packages_dir);
    PyObject *py_app = PyUnicode_DecodeFSDefault(app_dir);
    if (!py_sp || !py_app) {
        Py_XDECREF(py_sp);
        Py_XDECREF(py_app);
        Py_DECREF(globals);
        return -1;
    }
    int rc = PyDict_SetItemString(globals, "_M7A_SP", py_sp);
    rc |= PyDict_SetItemString(globals, "_M7A_APP", py_app);
    Py_DECREF(py_sp);
    Py_DECREF(py_app);
    if (rc != 0) {
        Py_DECREF(globals);
        return -1;
    }

    static const char *script =
        "import os, site, sys\n"
        "_sp = os.path.normpath(_M7A_SP)\n"
        "_before = len(sys.path)\n"
        "if os.path.isdir(_sp):\n"
        "    site.addsitedir(_sp)\n"
        "_added = sys.path[_before:]\n"
        "if _added:\n"
        "    del sys.path[_before:]\n"
        "    _idx = 1 if len(sys.path) >= 1 else 0\n"
        "    sys.path[_idx:_idx] = _added\n"
        "_app = os.path.normpath(_M7A_APP)\n"
        "if os.path.isdir(_app) and _app not in sys.path:\n"
        "    sys.path.append(_app)\n"
        "del _sp, _before, _added, _app\n";

    PyObject *res = PyRun_String(script, Py_file_input, globals, globals);
    Py_DECREF(globals);
    if (!res) {
        PyErr_Print();
        return -1;
    }
    Py_DECREF(res);
    return 0;
}

int main(int argc, char *argv[]) {
    char exe_path[M7A_PATH_BUF];
    if (resolve_executable_path(exe_path, sizeof(exe_path)) != 0) {
        fprintf(stderr, "March7thAssistant: failed to resolve executable path\n");
        return 1;
    }

    char contents_dir[M7A_PATH_BUF];
#if M7A_GUI_MODE
    const int strip_levels = 2; /* .../Contents/MacOS/March7thAssistant -> .../Contents */
#else
    const int strip_levels = 5; /* .../Contents/Helpers/March7thWorker.app/Contents/MacOS/March7thWorker -> .../Contents */
#endif
    if (strip_path_components(exe_path, strip_levels, contents_dir, sizeof(contents_dir)) != 0) {
        fprintf(stderr, "March7thAssistant: failed to locate Contents directory from %s\n", exe_path);
        return 1;
    }

    char python_home[M7A_PATH_BUF];
    char app_dir[M7A_PATH_BUF];
    char site_packages_dir[M7A_PATH_BUF];
    char worker_bin[M7A_PATH_BUF];
    char app_py[M7A_PATH_BUF];

    if (snprintf(python_home, sizeof(python_home), "%s/Frameworks/Python.framework/Versions/3.12", contents_dir) >= (int)sizeof(python_home) ||
        snprintf(app_dir, sizeof(app_dir), "%s/Resources/app", contents_dir) >= (int)sizeof(app_dir) ||
        snprintf(site_packages_dir, sizeof(site_packages_dir), "%s/Resources/site-packages", contents_dir) >= (int)sizeof(site_packages_dir) ||
        snprintf(worker_bin, sizeof(worker_bin), "%s/Helpers/March7thWorker.app/Contents/MacOS/March7thWorker", contents_dir) >= (int)sizeof(worker_bin) ||
        snprintf(app_py, sizeof(app_py), "%s/app.py", app_dir) >= (int)sizeof(app_py)) {
        fprintf(stderr, "March7thAssistant: bundle path too long\n");
        return 1;
    }

    unsetenv("PYTHONHOME");
    setenv("PYTHONNOUSERSITE", "1", 1);
    setenv("PYTHONDONTWRITEBYTECODE", "1", 1);
    setenv("PYTHONUTF8", "1", 1);
    setenv("PYTHONIOENCODING", "utf-8", 1);
    setenv("M7A_WORKER_PYTHON", worker_bin, 1);
    ensure_system_path();
    redirect_gui_stdio_if_needed();

    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    config.user_site_directory = 0;
    config.write_bytecode = 0;

    PyStatus status = PyConfig_SetBytesString(&config, &config.program_name, exe_path);
    if (!PyStatus_Exception(status)) {
        status = PyConfig_SetBytesString(&config, &config.home, python_home);
    }

#if M7A_GUI_MODE
    char **gui_argv = (char **)calloc((size_t)argc + 2, sizeof(char *));
    if (!gui_argv) {
        PyConfig_Clear(&config);
        fprintf(stderr, "March7thAssistant: out of memory\n");
        return 1;
    }
    int gui_argc = 0;
    gui_argv[gui_argc++] = exe_path;
    gui_argv[gui_argc++] = app_py;
    for (int i = 1; i < argc; i++) {
        if (strncmp(argv[i], "-psn_", 5) == 0) {
            continue;
        }
        gui_argv[gui_argc++] = argv[i];
    }
    if (!PyStatus_Exception(status)) {
        status = PyConfig_SetBytesArgv(&config, gui_argc, gui_argv);
    }
    free(gui_argv);
#else
    if (!PyStatus_Exception(status)) {
        status = PyConfig_SetBytesArgv(&config, argc, argv);
    }
#endif

    if (PyStatus_Exception(status)) {
        PyConfig_Clear(&config);
        Py_ExitStatusException(status);
    }

    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) {
        Py_ExitStatusException(status);
    }

    if (inject_bundle_paths(site_packages_dir, app_dir) != 0) {
        Py_FinalizeEx();
        return 1;
    }

    return Py_RunMain();
}
