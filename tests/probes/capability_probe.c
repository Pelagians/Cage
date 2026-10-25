/* Windows filesystem + TCP + HID enumeration observations. Disposable paths only.
 * Build: x86_64-w64-mingw32-gcc -municode capability_probe.c -o probe.exe -lws2_32 -lsetupapi -lhid
 * Usage: probe.exe READ_CANARY WRITABLE_DIRECTORY DENIED_CANARY PROTECTED_CANARY [TCP_PORT]
 * Output is evidence for a host-side assertion, never a hardware compatibility pass.
 */
#define UNICODE
#define _UNICODE
#include <winsock2.h>
#include <windows.h>
#include <setupapi.h>
#include <hidsdi.h>
#include <stdio.h>
#include <wchar.h>
#include <string.h>

static int read_canary(const wchar_t *path) {
    char buffer[64]={0};DWORD count=0;
    HANDLE f=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);
    if(f==INVALID_HANDLE_VALUE)return 0;
    int ok=ReadFile(f,buffer,sizeof(buffer),&count,NULL);CloseHandle(f);
    return ok && count==18 && memcmp(buffer,"cage-probe-canary\n",18)==0;
}
static int writable(const wchar_t *directory) {
    wchar_t name[4096],renamed[4096];DWORD count=0;
    if(swprintf(name,4096,L"%ls\\cage-parity-%lu.tmp",directory,GetCurrentProcessId())<0)return 0;
    if(swprintf(renamed,4096,L"%ls.renamed",name)<0)return 0;
    HANDLE f=CreateFileW(name,GENERIC_WRITE,0,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
    if(f==INVALID_HANDLE_VALUE)return 0;
    int ok=WriteFile(f,"cage-parity-write\n",18,&count,NULL) && FlushFileBuffers(f);CloseHandle(f);
    ok=ok && MoveFileW(name,renamed);
    if(ok)ok=DeleteFileW(renamed);
    DeleteFileW(name);return ok;
}
static unsigned hid_count(void) {
    GUID guid;HidD_GetHidGuid(&guid);
    HDEVINFO info=SetupDiGetClassDevsW(&guid,NULL,NULL,DIGCF_PRESENT|DIGCF_DEVICEINTERFACE);
    if(info==INVALID_HANDLE_VALUE)return 0;
    SP_DEVICE_INTERFACE_DATA data;data.cbSize=sizeof(data);unsigned count=0;
    while(SetupDiEnumDeviceInterfaces(info,NULL,&guid,count,&data))++count;
    SetupDiDestroyDeviceInfoList(info);return count;
}
static int tcp(int port) {
    WSADATA data;if(WSAStartup(MAKEWORD(2,2),&data))return 0;
    SOCKET s=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);if(s==INVALID_SOCKET){WSACleanup();return 0;}
    struct sockaddr_in addr={0};addr.sin_family=AF_INET;addr.sin_port=htons((u_short)port);addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    DWORD timeout=2000;setsockopt(s,SOL_SOCKET,SO_RCVTIMEO,(char *)&timeout,sizeof(timeout));
    char buffer[64]={0};int ok=connect(s,(struct sockaddr *)&addr,sizeof(addr))==0;
    if(ok)ok=send(s,"cage-parity-ping\n",17,0)==17 && recv(s,buffer,64,0)==17 && memcmp(buffer,"cage-parity-pong\n",17)==0;
    closesocket(s);WSACleanup();return ok;
}
int wmain(int argc,wchar_t **argv) {
    if(argc<5 || argc>6)return 2;
    printf("{\"schemaVersion\":\"cage.windows-capability-probe/v1\",\"status\":\"observed\",\"filesystem\":{\"read\":%s,\"write\":%s,\"siblingRead\":%s,\"protectedRead\":%s},\"network\":{\"tcp\":%s},\"hidInterfaces\":%u}\n",
      read_canary(argv[1])?"true":"false",writable(argv[2])?"true":"false",read_canary(argv[3])?"true":"false",read_canary(argv[4])?"true":"false",
      argc==6?(tcp(_wtoi(argv[5]))?"true":"false"):"null",hid_count());
    return 0;
}
