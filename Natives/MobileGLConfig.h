#pragma once

#import <Foundation/Foundation.h>

@interface MobileGLConfig : NSObject

+ (void)applyEnvironmentFromPreferences;
+ (NSString *)activeConfigSummary;
// MobileGlues reads config.json instead of environment variables
+ (void)applyMobileGluesConfigInDirectory:(NSString *)dir;

@end
