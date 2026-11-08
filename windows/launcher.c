/* PrintWatch.exe: runs files\runtime\python.exe files\start.py in this console window. */
#include <windows.h>
#include <stdio.h>
#include <wchar.h>

int wmain(int argc, wchar_t **argv) {
    wchar_t dir[MAX_PATH], cmd[4096], path[32768], newpath[34000];
    CreateMutexW(NULL, TRUE, L"Local\\PrintWatchRunning");
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        MessageBoxW(NULL, L"PrintWatch is already running (look for its window on the taskbar).", L"PrintWatch", MB_OK | MB_ICONINFORMATION);
        return 0;
    }
    SetConsoleTitleW(L"PrintWatch - keep this window open");
    GetModuleFileNameW(NULL, dir, MAX_PATH);
    wchar_t *s = wcsrchr(dir, L'\\'); if (s) *s = 0;
    DWORD n = GetEnvironmentVariableW(L"PATH", path, 32768); if (!n) path[0] = 0;
    swprintf(newpath, 34000, L"%ls\\files\\runtime;%ls\\files\\runtime\\Library\\bin;%ls", dir, dir, path);
    SetEnvironmentVariableW(L"PATH", newpath);
    SetEnvironmentVariableW(L"PYTHONNOUSERSITE", L"1");
    SetEnvironmentVariableW(L"PYTHONUTF8", L"1");
    swprintf(cmd, 4096, L"\"%ls\\files\\runtime\\python.exe\" -u \"%ls\\files\\start.py\"", dir, dir);
    for (int i = 1; i < argc; i++) { wcscat(cmd, L" \""); wcscat(cmd, argv[i]); wcscat(cmd, L"\""); }
    STARTUPINFOW si = { sizeof si }; PROCESS_INFORMATION pi;
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput = GetStdHandle(STD_INPUT_HANDLE); si.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE); si.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    /* everything started from here (Python and the web link server) closes when this window closes */
    HANDLE job = CreateJobObjectW(NULL, NULL);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION li = {0};
    li.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (job) SetInformationJobObject(job, JobObjectExtendedLimitInformation, &li, sizeof li);
    if (!CreateProcessW(NULL, cmd, NULL, NULL, TRUE, CREATE_SUSPENDED, NULL, dir, &si, &pi)) {
        fwprintf(stderr, L"Couldn't start Python in %ls\\files\\runtime (error %lu).\nPress Enter to close.", dir, GetLastError());
        getchar(); return 1;
    }
    if (job) AssignProcessToJobObject(job, pi.hProcess);
    ResumeThread(pi.hThread);
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 0; GetExitCodeProcess(pi.hProcess, &code);
    return (int)code;
}
