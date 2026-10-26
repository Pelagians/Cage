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
#define IDM_FILE_SAVE 41006

static const char original[] = "Original macOS document\n";
static const char first[] = "Cage macOS saved through Notepad++\n";
static const char second[] = "Relaunch verified\n";
static DWORD app_pid;
static HWND main_window, editor;
static RECT window_bounds;

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
    wchar_t name[128]; DWORD pid = 0; (void)unused;
    GetWindowThreadProcessId(window, &pid);
    GetClassNameW(window, name, 128);
    if (pid == app_pid && !wcscmp(name, L"Notepad++") && IsWindowVisible(window)) {
        main_window = window;
        EnumChildWindows(window, find_editor, 0);
    }
    return TRUE;
}

static int matches(const char *expected) {
    size_t length = strlen(expected);
    if (message(editor, SCI_GETLENGTH, 0, 0) != (LRESULT)length) return 0;
    for (size_t i = 0; i < length; ++i)
        if (message(editor, SCI_GETCHARAT, (WPARAM)i, 0) != (unsigned char)expected[i]) return 0;
    return 1;
}

static int receipt(const wchar_t *path, int round, const char *phase, DWORD exit_code) {
    FILE *file = _wfopen(path, L"wb");
    if (!file) return 0;
    fprintf(file, "{\"schemaVersion\":\"cage.notepad-gui-probe/v0\",\"round\":%d,"
            "\"phase\":\"%s\",\"applicationPid\":%lu,\"visibleEditor\":true,"
            "\"initialTextVerified\":true,\"editedTextVerified\":true,"
            "\"zoom\":3,\"windowWidth\":%ld,\"windowHeight\":%ld,"
            "\"applicationExitCode\":%lu}\n", round, phase, app_pid,
            window_bounds.right - window_bounds.left, window_bounds.bottom - window_bounds.top, exit_code);
    return fclose(file) == 0;
}

int wmain(int argc, wchar_t **argv) {
    if (argc != 5 || (wcscmp(argv[1], L"1") && wcscmp(argv[1], L"2"))) return 2;
    int round = _wtoi(argv[1]);
    wchar_t command[32768], ready[32768], close_request[32768];
    if (wcschr(argv[2], L'"') || wcschr(argv[3], L'"')) return 3;
    if (swprintf(command, 32768, L"\"%ls\" -multiInst -nosession -noPlugin \"%ls\"", argv[2], argv[3]) < 0
        || swprintf(ready, 32768, L"%ls.ready", argv[4]) < 0
        || swprintf(close_request, 32768, L"%ls.close", argv[4]) < 0) return 4;
    STARTUPINFOW startup = {0}; PROCESS_INFORMATION process = {0}; startup.cb = sizeof(startup);
    if (!CreateProcessW(argv[2], command, NULL, NULL, FALSE, 0, NULL, NULL, &startup, &process)) {
        fprintf(stderr, "CreateProcess: %lu\n", GetLastError()); return 5;
    }
    app_pid = process.dwProcessId;
    ULONGLONG start = GetTickCount64();
    while (GetTickCount64() - start < 90000) {
        EnumWindows(find_main, 0);
        if (editor && matches(round == 1 ? original : first)) break;
        if (WaitForSingleObject(process.hProcess, 0) == WAIT_OBJECT_0) return 6;
        Sleep(100);
    }
    if (!main_window || !editor || !matches(round == 1 ? original : first)) return 7;
    GetWindowRect(main_window, &window_bounds);
    if (window_bounds.right <= window_bounds.left || window_bounds.bottom <= window_bounds.top) return 8;
    /* Verify settings were loaded by the new process before editing again. */
    if (round == 2 && message(editor, SCI_GETZOOM, 0, 0) != 3) return 9;
    message(editor, SCI_SETZOOM, 3, 0);
    if (round == 1) message(editor, SCI_SELECTALL, 0, 0);
    else message(editor, SCI_GOTOPOS, (WPARAM)message(editor, SCI_GETLENGTH, 0, 0), 0);
    const char *text = round == 1 ? first : second;
    for (size_t i = 0; text[i]; ++i) {
        if (text[i] == '\n') {
            message(editor, WM_KEYDOWN, VK_RETURN, 1);
            message(editor, WM_KEYUP, VK_RETURN, 1);
        } else message(editor, WM_CHAR, (WPARAM)text[i], 1);
    }
    char expected[256]; snprintf(expected, sizeof(expected), "%s%s", first, round == 2 ? second : "");
    if (!matches(expected) || message(editor, SCI_GETZOOM, 0, 0) != 3) return 10;
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
    CloseHandle(process.hThread); CloseHandle(process.hProcess);
    if (exit_code) return 14;
    return receipt(argv[4], round, "closed", exit_code) ? 0 : 15;
}
