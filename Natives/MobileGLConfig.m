#import "MobileGLConfig.h"
#import "LauncherPreferences.h"

extern char **environ;

// pref, env var, value it gets when the pref is on
static NSArray<NSArray<NSString *> *> *envTable(void) {
    return @[
        @[@"video.mobilegl_fast_shader_load", @"MOBILEGL_ASYNC_OPTIMISTIC_SHADER_STATUS", @"1"],
        @[@"video.mobilegl_buffer_compat", @"MOBILEGL_COHERENT_AS_FLUSH", @"1"],
        @[@"video.mobilegl_relaxed", @"MOBILEGL_RELAXED_SEMANTICS", @"1"],
    ];
}

@implementation MobileGLConfig

+ (void)applyEnvironmentFromPreferences {
    setenv("MOBILEGL_BACKEND_TYPE", "DirectVulkan", 1);

    const char *home = getenv("AME_HOME");
    if (home && *home) {
        NSString *log = [NSString stringWithFormat:@"%s/mobilegl.log", home];
        setenv("MOBILEGL_LOG_FILE_PATH", log.UTF8String, 1);
    }

    // overwrite = 0, whatever's in the java env vars field wins
    for (NSArray<NSString *> *row in envTable()) {
        if (getPrefBool(row[0])) setenv(row[1].UTF8String, row[2].UTF8String, 0);
    }
}

+ (NSString *)activeConfigSummary {
    NSMutableArray *vars = [NSMutableArray new];
    for (char **e = environ; *e; e++) {
        if (strncmp(*e, "MOBILEGL_", 9) == 0) [vars addObject:@(*e)];
    }
    [vars sortUsingSelector:@selector(compare:)];
    return [vars componentsJoinedByString:@" "];
}

+ (void)applyMobileGluesConfigInDirectory:(NSString *)dir {
    NSString *path = [dir stringByAppendingPathComponent:@"config.json"];

    // Merge into whatever is already there, so keys MobileGlues manages itself are kept
    NSMutableDictionary *config = nil;
    NSData *data = [NSData dataWithContentsOfFile:path];
    if (data) {
        id obj = [NSJSONSerialization JSONObjectWithData:data options:NSJSONReadingMutableContainers error:nil];
        if ([obj isKindOfClass:NSMutableDictionary.class]) config = obj;
    }

    // 0 = off, 1-4 = Ultra Quality, Quality, Balanced, Performance
    NSInteger fsr = MAX(0, MIN(4, getPrefInt(@"video.mobileglues_fsr1")));

    // Always log what was read, so a missing or ignored setting can be told apart in latestlog.txt
    NSLog(@"[MobileGluesConfig] dir=%@ slider=%ld existingFile=%d existingFsr=%@",
          dir, (long)fsr, config != nil, config[@"fsr1Setting"] ?: @"(none)");

    // Nothing set and no file yet: leave MobileGlues on its own defaults
    if (!config && fsr == 0) return;
    if (!config) config = [NSMutableDictionary new];
    if (config[@"fsr1Setting"] && [config[@"fsr1Setting"] integerValue] == fsr) return;

    config[@"fsr1Setting"] = @(fsr);
    NSData *out = [NSJSONSerialization dataWithJSONObject:config options:NSJSONWritingPrettyPrinted error:nil];
    if ([out writeToFile:path atomically:YES]) {
        NSLog(@"[MobileGluesConfig] fsr1Setting = %ld", (long)fsr);
    } else {
        NSLog(@"[MobileGluesConfig] could not write %@", path);
    }
}

@end
