/* Local CI fixture mode. Launches a native child through Wine's CreateProcess
 * Unix-executable path, then records Windows observations and prefix state.
 * Configuration is a bounded UTF-8 line protocol in a read-only granted folder.
 */
static int runtime_parity(const wchar_t *config, const wchar_t *document) {
    wchar_t values[12][16384];char line[32768];
    FILE *f=_wfopen(config,L"rb");if(!f)return 20;
    for(int i=0;i<12;i++) {
        if(!fgets(line,sizeof(line),f)){fclose(f);return 21;}
        line[strcspn(line,"\r\n")]=0;
        if(!MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,line,-1,values[i],16384)){fclose(f);return 22;}
    }
    fclose(f);
    if(wcscmp(values[0],L"cage-runtime-probe/v1"))return 23;
    HWND window=CreateWindowExW(0,L"STATIC",L"Cage Runtime Parity",WS_OVERLAPPEDWINDOW|WS_VISIBLE,
                                40,40,520,220,NULL,NULL,GetModuleHandleW(NULL),NULL);
    if(!window)return 24;
    ShowWindow(window,SW_SHOW);UpdateWindow(window);
    STARTUPINFOW startup={0};PROCESS_INFORMATION process={0};startup.cb=sizeof(startup);
    /* argv[0] is a Unix path for CPython's relocation logic; applicationName
     * is its Windows Z: spelling for Wine's executable lookup. No shell. */
    if(!CreateProcessW(values[7],values[8],NULL,NULL,FALSE,0,NULL,NULL,&startup,&process)) {
        fprintf(stderr,"native CreateProcess failed: %lu\n",GetLastError());return 25;
    }
    if(process.hThread)CloseHandle(process.hThread);
    if(process.hProcess)CloseHandle(process.hProcess);
    ULONGLONG start=GetTickCount64();int child_ready=0;
    while(GetTickCount64()-start<120000) {
        MSG message;
        while(PeekMessageW(&message,NULL,0,0,PM_REMOVE)){TranslateMessage(&message);DispatchMessageW(&message);}
        child_ready=GetFileAttributesW(values[9])!=INVALID_FILE_ATTRIBUTES;
        if(child_ready && GetFileAttributesW(values[11])!=INVALID_FILE_ATTRIBUTES && GetTickCount64()-start>2500)break;
        Sleep(30);
    }
    if(!child_ready)return 26;
    /* A stable user preference is independent of the advancing launch count. */
    static const char preference_value[]="cage-user-preference-v1\n";
    const size_t preference_size=sizeof(preference_value)-1;
    char preference[sizeof(preference_value)]={0};
    f=_wfopen(L"C:\\cage-parity-preference.txt",L"rb");
    if(f){if(fread(preference,1,preference_size,f)!=preference_size){fclose(f);return 33;}fclose(f);}
    else {
        f=_wfopen(L"C:\\cage-parity-preference.txt",L"wb");if(!f)return 34;
        if(fwrite(preference_value,1,preference_size,f)!=preference_size){fclose(f);return 35;}fclose(f);
        memcpy(preference,preference_value,preference_size);
    }
    int settings_preserved=memcmp(preference,preference_value,preference_size)==0;
    if(!settings_preserved)return 36;
    int forwarded=document?read_canary(document):0;
    unsigned counter=0;
    f=_wfopen(L"C:\\cage-parity-state.txt",L"rb");
    if(f){if(fscanf(f,"%u",&counter)!=1){fclose(f);return 27;}fclose(f);}
    f=_wfopen(L"C:\\cage-parity-state.txt",L"wb");if(!f)return 28;
    fprintf(f,"%u\n",++counter);if(fclose(f))return 29;
    wchar_t parent[16384];wcscpy(parent,values[1]);
    wchar_t *last=wcsrchr(parent,L'/'),*back=wcsrchr(parent,L'\\');
    if(back && (!last || back>last))last=back;
    if(!last)return 30;
    *last=0;
    int read=read_canary(values[1]),read_mutation=writable(parent),write=writable(values[2]);
    int denied=read_canary(values[3]),protected_read=read_canary(values[4]),old=read_canary(values[5]);
    int network=tcp(_wtoi(values[6]));unsigned hids=hid_count();
    f=_wfopen(values[10],L"wb");if(!f)return 31;
    fprintf(f,"{\"schemaVersion\":\"cage.windows-capability-probe/v1\",\"status\":\"observed\","
        "\"filesystem\":{\"read\":%s,\"readScopeMutation\":%s,\"write\":%s,\"siblingRead\":%s,\"protectedRead\":%s,\"previousRead\":%s},"
        "\"network\":{\"tcp\":%s},\"wineDriveWrite\":%s,\"hidInterfaces\":%u,\"stateCounter\":%u,\"settingsPreserved\":%s,\"forwardedDocumentReadable\":%s,\"windowCreated\":true,\"nativeChildCompleted\":true}\n",
        read?"true":"false",read_mutation?"true":"false",write?"true":"false",denied?"true":"false",
        protected_read?"true":"false",old?"true":"false",network?"true":"false",writable(L"H:\\")?"true":"false",hids,counter,settings_preserved?"true":"false",document?(forwarded?"true":"false"):"null");
    if(fclose(f))return 32;
    DestroyWindow(window);return 0;
}
