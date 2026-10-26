/* Local .app host. Cage owns Wine execution and the persistent state lifecycle. */
#import <AppKit/AppKit.h>
#include <stdlib.h>
#include <string.h>

static int verifyBundle(NSString *path) {
    NSTask *check = [NSTask new];
    check.executableURL = [NSURL fileURLWithPath:@"/usr/bin/codesign"];
    check.arguments = @[@"--verify", @"--deep", @"--strict", path];
    NSError *error = nil;
    if (![check launchAndReturnError:&error]) { NSLog(@"%@", error); return 65; }
    [check waitUntilExit];
    return check.terminationStatus;
}

static void showError(NSString *message) {
    NSAlert *alert = [NSAlert new];
    alert.messageText = @"Cage could not run this application";
    alert.informativeText = message;
    [alert runModal];
}

@interface CageHost : NSObject <NSApplicationDelegate>
@property(nonatomic, strong) NSMutableArray<NSString *> *files;
@property(nonatomic, strong) NSTask *child;
@property(nonatomic, strong) NSFileHandle *log;
@property(nonatomic, copy) NSString *logPath;
@end

@implementation CageHost
- (void)application:(NSApplication *)sender openFiles:(NSArray<NSString *> *)files {
    if (self.child) {
        [sender replyToOpenOrPrint:NSApplicationDelegateReplyFailure];
        showError(@"Close the application window before opening another document from Finder.");
        return;
    }
    [self.files addObjectsFromArray:files];
    [sender replyToOpenOrPrint:NSApplicationDelegateReplySuccess];
}
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    (void)notification;
    [self performSelector:@selector(start) withObject:nil afterDelay:0];
}
- (void)start {
    NSBundle *bundle = NSBundle.mainBundle;
    NSString *directory = [[NSHomeDirectory() stringByAppendingPathComponent:@"Library/Logs/Cage"]
                           stringByAppendingPathComponent:bundle.bundleIdentifier];
    NSError *error = nil;
    if (![NSFileManager.defaultManager createDirectoryAtPath:directory withIntermediateDirectories:YES attributes:nil error:&error]) {
        showError(error.localizedDescription); exit(1);
    }
    self.logPath = [directory stringByAppendingPathComponent:@"app-launch.log"];
    if (![NSFileManager.defaultManager fileExistsAtPath:self.logPath])
        [NSFileManager.defaultManager createFileAtPath:self.logPath contents:nil attributes:nil];
    self.log = [NSFileHandle fileHandleForWritingAtPath:self.logPath];
    if (!self.log) { showError(@"Cannot open the application launch log."); exit(1); }
    [self.log seekToEndOfFile];
    NSString *resources = bundle.resourcePath;
    self.child = [NSTask new];
    self.child.executableURL = [NSURL fileURLWithPath:[resources stringByAppendingPathComponent:@"python/bin/python3.13"]];
    self.child.arguments = [@[@"-I", @"-B", [resources stringByAppendingPathComponent:@"entry.py"]]
                            arrayByAddingObjectsFromArray:self.files];
    self.child.currentDirectoryURL = [NSURL fileURLWithPath:resources];
    NSMutableDictionary *environment = [NSMutableDictionary dictionaryWithDictionary:@{@"HOME":NSHomeDirectory(), @"PATH":@"/usr/bin:/bin:/usr/sbin:/sbin"}];
    NSDictionary *inherited = NSProcessInfo.processInfo.environment;
    for (NSString *key in @[@"USER", @"LOGNAME", @"LANG", @"LC_ALL", @"LC_CTYPE", @"__CF_USER_TEXT_ENCODING"])
        if (inherited[key]) environment[key] = inherited[key];
    self.child.environment = environment;
    self.child.standardOutput = self.log;
    self.child.standardError = self.log;
    __weak CageHost *weakHost = self;
    self.child.terminationHandler = ^(NSTask *task) {
        int status = task.terminationStatus;
        dispatch_async(dispatch_get_main_queue(), ^{
            CageHost *host = weakHost;
            [host.log closeFile];
            if (status) showError([@"Existing documents and settings were retained. See the launch log: " stringByAppendingString:host.logPath]);
            exit(status);
        });
    };
    if (![self.child launchAndReturnError:&error]) {
        [self.log closeFile]; showError(error.localizedDescription); exit(1);
    }
}
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
    (void)sender;
    if (self.child.running) {
        showError(@"Close the application window first so it can save its settings and shut down normally.");
        return NSTerminateCancel;
    }
    return NSTerminateNow;
}
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        int signature = verifyBundle(NSBundle.mainBundle.bundlePath);
        BOOL checkOnly = argc == 2 && strcmp(argv[1], "--cage-verify") == 0;
        if (checkOnly) return signature;
        NSApplication *application = NSApplication.sharedApplication;
        [application setActivationPolicy:NSApplicationActivationPolicyAccessory];
        if (signature) { showError(@"The application package has changed. Restore the original package before launching; existing state was retained."); return signature; }
        __attribute__((objc_precise_lifetime)) CageHost *host = [CageHost new];
        host.files = [NSMutableArray new];
        for (int index = 1; index < argc; ++index) {
            NSString *argument = [NSString stringWithUTF8String:argv[index]];
            if (![argument hasPrefix:@"-psn_"]) [host.files addObject:argument];
        }
        application.delegate = host;
        [application run];
    }
    return 0;
}
