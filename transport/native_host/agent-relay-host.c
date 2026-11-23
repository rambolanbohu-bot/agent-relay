/*
 * Agent Relay Skill v1.0.0-rc3 — Native Messaging host launcher
 * (agent-relay-host.c).
 *
 * Correction 1 (ChatGPT RC3 review): on Windows, Chrome's Native
 * Messaging host manifest "path" MUST point to an executable (.exe).
 * A batch wrapper (.bat) is NOT a reliable launch scheme and must not
 * be used. This small C launcher is the .exe:
 *
 *   Chrome Extension -> Native Messaging -> agent-relay-host.exe
 *                    -> python.exe transport/native_host.py
 *                    -> orchestrator/run.py (file queue)
 *
 * The launcher does ONE thing: find python.exe (via the py launcher
 * first, then python.exe on PATH), start native_host.py with the
 * skill's native-host state directory, and pass stdin/stdout through
 * untouched. The Native Messaging length-prefixed JSON protocol flows
 * through the launcher byte-for-byte.
 *
 * Rules the launcher obeys:
 * - It writes NOTHING to stdout (stdout belongs to the protocol).
 * - Errors go to agent-relay-host.log next to this .exe (and to
 *   stderr, which Chrome discards). Never to stdout.
 * - No console window: built with -mwindows, and the child python.exe
 *   is started with CREATE_NO_WINDOW.
 * - No network, no registry, no file access beyond the log file and
 *   starting native_host.py. It cannot release an approval.
 *
 * Layout (installed by install.py):
 *   <skill>\transport\agent-relay-host.exe   <- this program
 *   <skill>\transport\native_host.py         <- the real host (Python)
 *   <skill>\orchestrator\state\native_host\  <- inbox/outbox/secret
 *
 * Build (cross-compile on Linux):
 *   x86_64-w64-mingw32-gcc -O2 -mwindows -o agent-relay-host.exe \
 *       agent-relay-host.c
 * Build (on real Windows, see build_host_exe.bat):
 *   gcc -O2 -mwindows -o agent-relay-host.exe agent-relay-host.c
 *   (mingw-w64)  OR  cl /O2 /Feagent-relay-host.exe agent-relay-host.c
 *   (MSVC; link with kernel32.lib user32.lib)
 */

/* -municode (mingw) already defines UNICODE; guard the defines so a
   plain build without -municode still gets the wide APIs. */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <stdio.h>
#include <strsafe.h>

#define MAX_CMD 4096

static void log_error(const wchar_t *exe_dir, const wchar_t *fmt, ...)
{
    wchar_t path[MAX_PATH];
    wchar_t line[2048];
    SYSTEMTIME st;
    va_list ap;
    HANDLE h;
    DWORD written;

    if (FAILED(StringCchPrintfW(path, MAX_PATH, L"%s\\agent-relay-host.log",
                                exe_dir)))
        return;
    GetLocalTime(&st);
    va_start(ap, fmt);
    {
        wchar_t msg[1600];
        StringCchVPrintfW(msg, 1600, fmt, ap);
        StringCchPrintfW(line, 2048,
            L"[%04d-%02d-%02d %02d:%02d:%02d] %s\r\n",
            st.wYear, st.wMonth, st.wDay,
            st.wHour, st.wMinute, st.wSecond, msg);
    }
    va_end(ap);
    h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ, NULL,
                    OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return;
    SetFilePointer(h, 0, NULL, FILE_END);
    WriteFile(h, line, (DWORD)wcslen(line) * sizeof(wchar_t), &written,
              NULL);
    CloseHandle(h);
}

/* Quote one command-line argument (handles spaces and quotes). */
static BOOL quote_arg(wchar_t *dst, size_t dst_chars, const wchar_t *arg)
{
    size_t i, n = 0;
    if (FAILED(StringCchCopyW(dst, dst_chars, L"\"")))
        return FALSE;
    n = 1;
    for (i = 0; arg[i]; i++) {
        if (arg[i] == L'"') {
            if (n + 2 >= dst_chars)
                return FALSE;
            dst[n++] = L'\\';
            dst[n++] = L'"';
        } else {
            if (n + 1 >= dst_chars)
                return FALSE;
            dst[n++] = arg[i];
        }
    }
    if (n + 1 >= dst_chars)
        return FALSE;
    dst[n++] = L'"';
    dst[n] = L'\0';
    return TRUE;
}

int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance,
                    PWSTR pCmdLine, int nCmdShow)
{
    wchar_t exe_path[MAX_PATH];
    wchar_t exe_dir[MAX_PATH];
    wchar_t skill_root[MAX_PATH];
    wchar_t script_path[MAX_PATH];
    wchar_t state_dir[MAX_PATH];
    wchar_t python_path[MAX_PATH];
    wchar_t py_path[MAX_PATH];
    wchar_t cmdline[MAX_CMD];
    wchar_t q_python[MAX_PATH + 4];
    wchar_t q_script[MAX_PATH + 4];
    wchar_t q_state[MAX_PATH + 4];
    wchar_t *slash;
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    DWORD exit_code = 1;
    BOOL ok;
    (void)hInstance;
    (void)hPrevInstance;
    (void)pCmdLine;
    (void)nCmdShow;

    /* Locate ourselves: <skill>\transport\agent-relay-host.exe */
    if (!GetModuleFileNameW(NULL, exe_path, MAX_PATH))
        return 1;
    if (FAILED(StringCchCopyW(exe_dir, MAX_PATH, exe_path)))
        return 1;
    slash = wcsrchr(exe_dir, L'\\');
    if (!slash)
        return 1;
    *slash = L'\0';  /* exe_dir = <skill>\transport */

    /* skill root = parent of transport\ */
    if (FAILED(StringCchCopyW(skill_root, MAX_PATH, exe_dir)))
        return 1;
    slash = wcsrchr(skill_root, L'\\');
    if (!slash)
        return 1;
    *slash = L'\0';  /* skill_root = <skill> */

    if (FAILED(StringCchPrintfW(script_path, MAX_PATH,
                                L"%s\\native_host.py", exe_dir))) {
        log_error(exe_dir, L"script path too long");
        return 1;
    }
    if (GetFileAttributesW(script_path) == INVALID_FILE_ATTRIBUTES) {
        log_error(exe_dir, L"native_host.py not found next to the .exe: %s",
                  script_path);
        return 1;
    }
    if (FAILED(StringCchPrintfW(state_dir, MAX_PATH,
                                L"%s\\orchestrator\\state\\native_host",
                                skill_root))) {
        log_error(exe_dir, L"state dir path too long");
        return 1;
    }

    /* Find Python: the py launcher first, then python.exe on PATH. */
    if (SearchPathW(NULL, L"py.exe", NULL, MAX_PATH, py_path, NULL)) {
        /* py.exe found; prefer "py -3" so the newest Python 3 is used. */
        if (FAILED(StringCchCopyW(python_path, MAX_PATH, py_path))) {
            log_error(exe_dir, L"python path too long");
            return 1;
        }
        if (!quote_arg(q_python, MAX_PATH + 4, python_path) ||
            !quote_arg(q_script, MAX_PATH + 4, script_path) ||
            !quote_arg(q_state, MAX_PATH + 4, state_dir)) {
            log_error(exe_dir, L"command line too long");
            return 1;
        }
        if (FAILED(StringCchPrintfW(cmdline, MAX_CMD,
                                    L"%s -3 %s --state-dir %s",
                                    q_python, q_script, q_state))) {
            log_error(exe_dir, L"command line too long");
            return 1;
        }
    } else if (SearchPathW(NULL, L"python.exe", NULL, MAX_PATH,
                           python_path, NULL)) {
        if (!quote_arg(q_python, MAX_PATH + 4, python_path) ||
            !quote_arg(q_script, MAX_PATH + 4, script_path) ||
            !quote_arg(q_state, MAX_PATH + 4, state_dir)) {
            log_error(exe_dir, L"command line too long");
            return 1;
        }
        if (FAILED(StringCchPrintfW(cmdline, MAX_CMD,
                                    L"%s %s --state-dir %s",
                                    q_python, q_script, q_state))) {
            log_error(exe_dir, L"command line too long");
            return 1;
        }
    } else {
        log_error(exe_dir,
                  L"no Python found: neither py.exe nor python.exe is on "
                  L"PATH. Install Python 3.8+ from python.org (check "
                  L"'Add python.exe to PATH') and restart Chrome.");
        return 1;
    }

    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    si.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    si.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    ZeroMemory(&pi, sizeof(pi));

    /* CREATE_NO_WINDOW: no console flash. stdin/stdout are the inherited
       pipes from Chrome, so the Native Messaging protocol flows through. */
    ok = CreateProcessW(NULL, cmdline, NULL, NULL, TRUE,
                        CREATE_NO_WINDOW, NULL, NULL, &si, &pi);
    if (!ok) {
        log_error(exe_dir, L"CreateProcess failed (error %lu) for: %s",
                  GetLastError(), cmdline);
        return 1;
    }
    WaitForSingleObject(pi.hProcess, INFINITE);
    if (!GetExitCodeProcess(pi.hProcess, &exit_code))
        exit_code = 1;
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return (int)exit_code;
}
