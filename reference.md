# 各技术栈审计维度速查表

## 构建配置文件速查

| 技术栈 | 构建配置文件 |
|--------|------------|
| C/C++ | CMakeLists.txt, Makefile, .vcxproj, .sln, BUILD.gn |
| Java/Android | build.gradle(.kts), settings.gradle, pom.xml, proguard-rules.pro |
| iOS | .xcodeproj, .xcworkspace, Podfile, Package.swift, Cartfile, .pbxproj |
| Web | package.json, webpack.config.*, vite.config.*, tsconfig.json, .babelrc |

## 依赖方式速查

| 技术栈 | 典型依赖方式 |
|--------|------------|
| C/C++ | 源码级 include、静态链接(.a/.lib)、动态链接(.so/.dll/.dylib)、运行时 dlopen |
| Java/Android | Gradle implementation/api、Maven 依赖、AAR 引用、JNI 加载 .so |
| iOS | CocoaPods pod 依赖、SPM package 依赖、Framework 嵌入(embed/link)、OC++ 桥接 C/C++ 库 |
| Web | npm dependencies/devDependencies、monorepo workspace 引用、动态 import()、Wasm 模块加载 |

## 源码文件类型速查

| 技术栈 | 需统计的文件扩展名 |
|--------|------------------|
| C/C++ | .c, .cpp, .cc, .cxx, .h, .hpp, .hxx |
| Java/Android | .java, .kt, res/layout/*.xml, res/drawable/*, .aidl |
| iOS | .m, .mm, .swift, .h, .storyboard, .xib, .xcassets |
| Web | .ts, .tsx, .js, .jsx, .vue, .svelte, .css, .scss, .less |

## 典型过时/技术债特征速查

| 技术栈 | 典型过时/技术债特征 |
|--------|-------------------|
| C/C++ | MFC/陈旧 Qt 窗体绑定、手写内存池/线程池重复造轮子、Win32 API 直接调用未封装、VS 中间产物(ipch/Debug/Release)残留 |
| Java/Android | Support Library 未迁 AndroidX、AsyncTask/Loader/IntentService、minSdk<21、God Activity、未使用 ViewBinding/DataBinding、古老 Gradle 插件版本 |
| iOS | 纯 OC 未迁 Swift、UIWebView、MRC 手动内存管理、巨型 Storyboard、deployment target 过低(< iOS 13)、Carthage 依赖管理、未使用 ARC 的 .m 文件 |
| Web | jQuery/AngularJS/Backbone 残留、Webpack 3 以下、大量 any 类型 TS、CommonJS 模块未迁 ESM、Gulp/Grunt 构建、未类型化的纯 JS |

## 数据搜集命令参考

```powershell
# Windows PowerShell - 目录结构与体量
Get-ChildItem -Path "D:\projects" -Recurse | Measure-Object -Property Length -Sum
Get-ChildItem -Path "D:\projects" -Recurse -Directory | Select-Object FullName

# 按扩展名统计文件数
Get-ChildItem -Path "D:\projects" -Recurse -Include *.cpp,*.h,*.c,*.hpp | Measure-Object
Get-ChildItem -Path "D:\projects" -Recurse -Include *.java,*.kt | Measure-Object
Get-ChildItem -Path "D:\projects" -Recurse -Include *.m,*.mm,*.swift | Measure-Object
Get-ChildItem -Path "D:\projects" -Recurse -Include *.ts,*.tsx,*.js,*.jsx,*.vue | Measure-Object
```

```bash
# Git 活跃度数据
git log --since="2 years ago" --format="%h %ad %s" --date=short
git shortlog -sn
git log --since="1 year ago" --oneline | wc -l

# 按目录统计最后修改时间
git log -1 --format="%ai" -- <module_path>
```
