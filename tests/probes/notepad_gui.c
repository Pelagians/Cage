/* CI-only x64 Windows GUI driver. All document edits and saves go through
 * Notepad++'s visible Scintilla/editor window; this program never writes the
 * document or the application's configuration itself. No injected DLLs.
 * Build with x86_64-w64-mingw32-gcc -municode -static ... -luser32.
 * Scintilla messages: https://www.scintilla.org/ScintillaDoc.html
 * Save command: Notepad++ v8.8.8 PowerEditor/src/menuCmdID.h.
 */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <stdio.h>
#include <wchar.h>
#include <string.h>

#define SCI_GETLENGTH 2006
#define SCI_GETCHARAT 2007
#define SCI_SELECTALL 2013
#define SCI_GOTOPOS 2025
#define SCI_SETZOOM 2373
#define SCI_GETZOOM 2374
#define SCI_GETREADONLY 2140
#define IDM_FILE_SAVE 41006

static const char original[] = "Original macOS document\n";
#define FIRST_TEXT "Cage macOS saved through Notepad++\n"
#define SECOND_TEXT FIRST_TEXT "Relaunch verified\n"
#define THIRD_TEXT SECOND_TEXT "Packaged launch verified\n"
#define FOURTH_TEXT THIRD_TEXT "Packaged relaunch verified\n"
static const char first[] = FIRST_TEXT;
static const char second[] = "Relaunch verified\n";
static const char third[] = "Packaged launch verified\n";
static const char fourth[] = "Packaged relaunch verified\n";
static DWORD app_pid;
static HWND main_window, editor;
static RECT window_bounds;
static int attach_mode;
static const wchar_t *document_name;

static LRESULT message(HWND window, UINT id, WPARAM w, LPARAM l) {
    DWORD_PTR result = 0;
    if (!SendMessageTimeoutW(window, id, w, l, SMTO_ABORTIFHUNG | SMTO_BLOCK, 5000, &result)) {
        fprintf(stderr, "GUI message %u failed: %lu\n", id, GetLastError());
        ExitProcess(30);
    }
    return (LRESULT)result;
}

static BOOL CALLBACK find_editor(HWND window, LPARAM unused) {
    wchar_t name[128]; (void)unused;
    GetClassNameW(window, name, 128);
    if (!wcscmp(name, L"Scintilla") && IsWindowVisible(window)) {
        editor = window;
        return FALSE;
    }
    return TRUE;
}

static BOOL CALLBACK find_main(HWND window, LPARAM unused) {
    wchar_t name[128], title[4096]; DWORD pid = 0; (void)unused;
    GetWindowThreadProcessId(window, &pid);
    GetClassNameW(window, name, 128);
    GetWindowTextW(window, title, 4096);
    if ((attach_mode ? wcsstr(title, document_name) != NULL : pid == app_pid)
            && !wcscmp(name, L"Notepad++") && IsWindowVisible(window)) {
        app_pid = pid;
        main_window = window;
        EnumChildWindows(window, find_editor, 0);
        return FALSE;
    }
    return TRUE;
}

static int registry_persistence(int round) {
    HKEY key; wchar_t seed[128]; DWORD size = sizeof(seed), type = 0, counter = 0;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, L"Software\\Cage\\NativeProof", 0, KEY_READ | KEY_WRITE, &key)) return 0;
    if (RegQueryValueExW(key, L"SeedValue", NULL, &type, (BYTE *)seed, &size)
            || type != REG_SZ || wcscmp(seed, L"recipe-ordered")) { RegCloseKey(key); return 0; }
    size = sizeof(counter);
    LSTATUS status = RegQueryValueExW(key, L"LaunchCount", NULL, &type, (BYTE *)&counter, &size);
    if ((round == 1 && status != ERROR_FILE_NOT_FOUND) || (round >= 2 && (status || type != REG_DWORD || counter != (DWORD)(round - 1)))) {
        RegCloseKey(key); return 0;
    }
    counter = (DWORD)round;
    status = RegSetValueExW(key, L"LaunchCount", 0, REG_DWORD, (BYTE *)&counter, sizeof(counter));
    RegCloseKey(key); return status == ERROR_SUCCESS;
}

static int matches(const char *expected) {
    size_t length = strlen(expected);
    if (message(editor, SCI_GETLENGTH, 0, 0) != (LRESULT)length) return 0;
    for (size_t i = 0; i < length; ++i)
        if (message(editor, SCI_GETCHARAT, (WPARAM)i, 0) != (unsigned char)expected[i]) return 0;
    return 1;
}

static void report_mismatch(int round, const char *expected) {
    LRESULT length = message(editor, SCI_GETLENGTH, 0, 0);
    fprintf(stderr, "Round %d editor mismatch: expected length %zu, actual %lld, zoom %lld, readonly %lld\n",
            round, strlen(expected), (long long)length,
            (long long)message(editor, SCI_GETZOOM, 0, 0),
            (long long)message(editor, SCI_GETREADONLY, 0, 0));
    fprintf(stderr, "Expected bytes:");
    for (size_t i = 0; expected[i]; ++i) fprintf(stderr, " %02x", (unsigned char)expected[i]);
    fprintf(stderr, "\nActual bytes (at most 256):");
    for (LRESULT i = 0; i < length && i < 256; ++i)
        fprintf(stderr, " %02x", (unsigned int)message(editor, SCI_GETCHARAT, (WPARAM)i, 0));
    fprintf(stderr, "\n");
}

static int receipt(const wchar_t *path, int round, const char *phase, DWORD exit_code) {
    FILE *file = _wfopen(path, L"wb");
    if (!file) return 0;
    fprintf(file, "{\"schemaVersion\":\"cage.notepad-gui-probe/v0\",\"round\":%d,"
            "\"phase\":\"%s\",\"applicationPid\":%lu,\"visibleEditor\":true,"
            "\"initialTextVerified\":true,\"editedTextVerified\":true,"
            "\"zoom\":3,\"windowWidth\":%ld,\"windowHeight\":%ld,"
            "\"applicationExitCode\":%lu,\"registrySeedVerified\":%s,\"launchCounter\":%d}\n", round, phase, app_pid,
            window_bounds.right - window_bounds.left, window_bounds.bottom - window_bounds.top, exit_code,
            attach_mode ? "true" : "false", attach_mode ? round : 0);
    return fclose(file) == 0;
}

int wmain(int argc, wchar_t **argv) {
    if (argc != 5) return 2;
    attach_mode = !wcscmp(argv[1], L"--attach");
    int round = _wtoi(argv[attach_mode ? 2 : 1]);
    if (round < 1 || round > (attach_mode ? 4 : 2)) return 2;
    const char *initial = round == 1 ? original : round == 2 ? first : round == 3 ? SECOND_TEXT : THIRD_TEXT;
    document_name = wcsrchr(argv[3], L'\\');
    document_name = document_name ? document_name + 1 : argv[3];
    wchar_t command[32768], ready[32768], close_request[32768];
    if (wcschr(argv[2], L'"') || wcschr(argv[3], L'"')) return 3;
    if (swprintf(command, 32768, L"\"%ls\" -multiInst -nosession -noPlugin \"%ls\"", argv[2], argv[3]) < 0
        || swprintf(ready, 32768, L"%ls.ready", argv[4]) < 0
        || swprintf(close_request, 32768, L"%ls.close", argv[4]) < 0) return 4;
    STARTUPINFOW startup = {0}; PROCESS_INFORMATION process = {0}; startup.cb = sizeof(startup);
    if (!attach_mode && !CreateProcessW(argv[2], command, NULL, NULL, FALSE, 0, NULL, NULL, &startup, &process)) {
        fprintf(stderr, "CreateProcess: %lu\n", GetLastError()); return 5;
    }
    app_pid = process.dwProcessId;
    ULONGLONG start = GetTickCount64();
    while (GetTickCount64() - start < 90000) {
        EnumWindows(find_main, 0);
        if (editor && matches(initial)) break;
        if (process.hProcess && WaitForSingleObject(process.hProcess, 0) == WAIT_OBJECT_0) return 6;
        Sleep(100);
    }
    if (!main_window || !editor || !matches(initial)) return 7;
    if (attach_mode) {
        process.hProcess = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, app_pid);
        if (!process.hProcess || !registry_persistence(round)) return 16;
    }
    GetWindowRect(main_window, &window_bounds);
    if (window_bounds.right <= window_bounds.left || window_bounds.bottom <= window_bounds.top) return 8;
    /* Verify settings were loaded by the new process before editing again. */
    if (round >= 2 && message(editor, SCI_GETZOOM, 0, 0) != 3) return 9;
    message(editor, SCI_SETZOOM, 3, 0);
    if (round == 1) message(editor, SCI_SELECTALL, 0, 0);
    else message(editor, SCI_GOTOPOS, (WPARAM)message(editor, SCI_GETLENGTH, 0, 0), 0);
    const char *text = round == 1 ? first : round == 2 ? second : round == 3 ? third : fourth;
    for (size_t i = 0; text[i]; ++i) {
        if (text[i] == '\n') {
            message(editor, WM_KEYDOWN, VK_RETURN, 1);
            message(editor, WM_KEYUP, VK_RETURN, 1);
        } else message(editor, WM_CHAR, (WPARAM)text[i], 1);
    }
    const char *expected = round == 1 ? FIRST_TEXT : round == 2 ? SECOND_TEXT : round == 3 ? THIRD_TEXT : FOURTH_TEXT;
    if (!matches(expected) || message(editor, SCI_GETZOOM, 0, 0) != 3) {
        report_mismatch(round, expected); return 10;
    }
    message(main_window, WM_COMMAND, IDM_FILE_SAVE, 0);
    if (!receipt(ready, round, "saved-awaiting-host-verification", STILL_ACTIVE)) return 11;
    start = GetTickCount64();
    while (GetFileAttributesW(close_request) == INVALID_FILE_ATTRIBUTES) {
        if (GetTickCount64() - start > 60000) return 12;
        Sleep(100);
    }
    message(main_window, WM_CLOSE, 0, 0);
    if (WaitForSingleObject(process.hProcess, 30000) != WAIT_OBJECT_0) return 13;
    DWORD exit_code = 1; GetExitCodeProcess(process.hProcess, &exit_code);
    if (process.hThread) CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    if (exit_code) return 14;
    return receipt(argv[4], round, "closed", exit_code) ? 0 : 15;
}
