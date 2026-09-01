; ModuleID = '/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/regmap_access.c'
source_filename = "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/regmap_access.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

; Function Attrs: nounwind uwtable
define dso_local void @regmap_access(ptr noundef %0, i32 noundef %1) local_unnamed_addr #0 !dbg !17 {
  %3 = alloca i32, align 4, !DIAssignID !36
  call void @llvm.dbg.assign(metadata i1 undef, metadata !27, metadata !DIExpression(), metadata !36, metadata ptr %3, metadata !DIExpression()), !dbg !37
  %4 = alloca [2 x i32], align 4, !DIAssignID !38
  call void @llvm.dbg.assign(metadata i1 undef, metadata !32, metadata !DIExpression(), metadata !38, metadata ptr %4, metadata !DIExpression()), !dbg !37
  tail call void @llvm.dbg.value(metadata ptr %0, metadata !25, metadata !DIExpression()), !dbg !37
  tail call void @llvm.dbg.value(metadata i32 %1, metadata !26, metadata !DIExpression()), !dbg !37
  call void @llvm.lifetime.start.p0(i64 4, ptr nonnull %3) #5, !dbg !39
  call void @llvm.lifetime.start.p0(i64 8, ptr nonnull %4) #5, !dbg !40
  %5 = call i32 @regmap_read(ptr noundef %0, i32 noundef %1, ptr noundef nonnull %3) #5, !dbg !41
  %6 = add i32 %1, 4, !dbg !42
  %7 = load i32, ptr %3, align 4, !dbg !43, !tbaa !44
  %8 = call i32 @regmap_write(ptr noundef %0, i32 noundef %6, i32 noundef %7) #5, !dbg !48
  %9 = add i32 %1, 8, !dbg !49
  call void @llvm.dbg.value(metadata ptr %0, metadata !50, metadata !DIExpression()), !dbg !59
  call void @llvm.dbg.value(metadata i32 %9, metadata !56, metadata !DIExpression()), !dbg !59
  call void @llvm.dbg.value(metadata i32 255, metadata !57, metadata !DIExpression()), !dbg !59
  call void @llvm.dbg.value(metadata i32 85, metadata !58, metadata !DIExpression()), !dbg !59
  %10 = call i32 @regmap_update_bits_base(ptr noundef %0, i32 noundef %9, i32 noundef 255, i32 noundef 85, ptr noundef null, i1 noundef zeroext false, i1 noundef zeroext false) #5, !dbg !61
  %11 = add i32 %1, 12, !dbg !62
  %12 = call i32 @regmap_bulk_read(ptr noundef %0, i32 noundef %11, ptr noundef nonnull %4, i64 noundef 2) #5, !dbg !63
  call void @llvm.lifetime.end.p0(i64 8, ptr nonnull %4) #5, !dbg !64
  call void @llvm.lifetime.end.p0(i64 4, ptr nonnull %3) #5, !dbg !64
  ret void, !dbg !64
}

; Function Attrs: mustprogress nocallback nofree nosync nounwind willreturn memory(argmem: readwrite)
declare void @llvm.lifetime.start.p0(i64 immarg, ptr nocapture) #1

declare !dbg !65 i32 @regmap_read(ptr noundef, i32 noundef, ptr noundef) local_unnamed_addr #2

declare !dbg !69 i32 @regmap_write(ptr noundef, i32 noundef, i32 noundef) local_unnamed_addr #2

declare !dbg !72 i32 @regmap_bulk_read(ptr noundef, i32 noundef, ptr noundef, i64 noundef) local_unnamed_addr #2

; Function Attrs: mustprogress nocallback nofree nosync nounwind willreturn memory(argmem: readwrite)
declare void @llvm.lifetime.end.p0(i64 immarg, ptr nocapture) #1

declare !dbg !82 i32 @regmap_update_bits_base(ptr noundef, i32 noundef, i32 noundef, i32 noundef, ptr noundef, i1 noundef zeroext, i1 noundef zeroext) local_unnamed_addr #2

; Function Attrs: mustprogress nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare void @llvm.dbg.assign(metadata, metadata, metadata, metadata, metadata, metadata) #3

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare void @llvm.dbg.value(metadata, metadata, metadata) #4

attributes #0 = { nounwind uwtable "min-legal-vector-width"="0" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #1 = { mustprogress nocallback nofree nosync nounwind willreturn memory(argmem: readwrite) }
attributes #2 = { "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #3 = { mustprogress nocallback nofree nosync nounwind speculatable willreturn memory(none) }
attributes #4 = { nocallback nofree nosync nounwind speculatable willreturn memory(none) }
attributes #5 = { nounwind }

!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!9, !10, !11, !12, !13, !14, !15}
!llvm.ident = !{!16}

!0 = distinct !DICompileUnit(language: DW_LANG_C11, file: !1, producer: "Ubuntu clang version 18.1.3 (1ubuntu1)", isOptimized: true, runtimeVersion: 0, emissionKind: FullDebug, enums: !2, splitDebugInlining: false, nameTableKind: None)
!1 = !DIFile(filename: "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/regmap_access.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "a8cd582dcc9904b93a6d3441ba729672")
!2 = !{!3}
!3 = !DICompositeType(tag: DW_TAG_enumeration_type, file: !4, line: 10, baseType: !5, size: 32, elements: !6)
!4 = !DIFile(filename: "vendor/linux/include/linux/stddef.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "af3b1fa3cc421a8dc700fd2913426ff2")
!5 = !DIBasicType(name: "unsigned int", size: 32, encoding: DW_ATE_unsigned)
!6 = !{!7, !8}
!7 = !DIEnumerator(name: "false", value: 0)
!8 = !DIEnumerator(name: "true", value: 1)
!9 = !{i32 7, !"Dwarf Version", i32 5}
!10 = !{i32 2, !"Debug Info Version", i32 3}
!11 = !{i32 1, !"wchar_size", i32 4}
!12 = !{i32 8, !"PIC Level", i32 2}
!13 = !{i32 7, !"PIE Level", i32 2}
!14 = !{i32 7, !"uwtable", i32 2}
!15 = !{i32 7, !"debug-info-assignment-tracking", i1 true}
!16 = !{!"Ubuntu clang version 18.1.3 (1ubuntu1)"}
!17 = distinct !DISubprogram(name: "regmap_access", scope: !18, file: !18, line: 3, type: !19, scopeLine: 4, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !24)
!18 = !DIFile(filename: "qa/tests/fixtures/regmap_access.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "a8cd582dcc9904b93a6d3441ba729672")
!19 = !DISubroutineType(types: !20)
!20 = !{null, !21, !5}
!21 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !22, size: 64)
!22 = !DICompositeType(tag: DW_TAG_structure_type, name: "regmap", file: !23, line: 36, flags: DIFlagFwdDecl)
!23 = !DIFile(filename: "vendor/linux/include/linux/regmap.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "d5222821fa51e3d7722910154940c474")
!24 = !{!25, !26, !27, !32}
!25 = !DILocalVariable(name: "map", arg: 1, scope: !17, file: !18, line: 3, type: !21)
!26 = !DILocalVariable(name: "reg", arg: 2, scope: !17, file: !18, line: 3, type: !5)
!27 = !DILocalVariable(name: "value", scope: !17, file: !18, line: 5, type: !28)
!28 = !DIDerivedType(tag: DW_TAG_typedef, name: "u32", file: !29, line: 21, baseType: !30)
!29 = !DIFile(filename: "vendor/linux/include/asm-generic/int-ll64.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "12ca7bdb629352cc4c9a492f86b435a7")
!30 = !DIDerivedType(tag: DW_TAG_typedef, name: "__u32", file: !31, line: 27, baseType: !5)
!31 = !DIFile(filename: "vendor/linux/include/uapi/asm-generic/int-ll64.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "f4d0ec5bcdd84e825a78a7add39d54dd")
!32 = !DILocalVariable(name: "values", scope: !17, file: !18, line: 6, type: !33)
!33 = !DICompositeType(tag: DW_TAG_array_type, baseType: !28, size: 64, elements: !34)
!34 = !{!35}
!35 = !DISubrange(count: 2)
!36 = distinct !DIAssignID()
!37 = !DILocation(line: 0, scope: !17)
!38 = distinct !DIAssignID()
!39 = !DILocation(line: 5, column: 2, scope: !17)
!40 = !DILocation(line: 6, column: 2, scope: !17)
!41 = !DILocation(line: 8, column: 2, scope: !17)
!42 = !DILocation(line: 9, column: 24, scope: !17)
!43 = !DILocation(line: 9, column: 29, scope: !17)
!44 = !{!45, !45, i64 0}
!45 = !{!"int", !46, i64 0}
!46 = !{!"omnipotent char", !47, i64 0}
!47 = !{!"Simple C/C++ TBAA"}
!48 = !DILocation(line: 9, column: 2, scope: !17)
!49 = !DILocation(line: 10, column: 30, scope: !17)
!50 = !DILocalVariable(name: "map", arg: 1, scope: !51, file: !23, line: 1341, type: !21)
!51 = distinct !DISubprogram(name: "regmap_update_bits", scope: !23, file: !23, line: 1341, type: !52, scopeLine: 1343, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagLocalToUnit | DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !55)
!52 = !DISubroutineType(types: !53)
!53 = !{!54, !21, !5, !5, !5}
!54 = !DIBasicType(name: "int", size: 32, encoding: DW_ATE_signed)
!55 = !{!50, !56, !57, !58}
!56 = !DILocalVariable(name: "reg", arg: 2, scope: !51, file: !23, line: 1341, type: !5)
!57 = !DILocalVariable(name: "mask", arg: 3, scope: !51, file: !23, line: 1342, type: !5)
!58 = !DILocalVariable(name: "val", arg: 4, scope: !51, file: !23, line: 1342, type: !5)
!59 = !DILocation(line: 0, scope: !51, inlinedAt: !60)
!60 = distinct !DILocation(line: 10, column: 2, scope: !17)
!61 = !DILocation(line: 1344, column: 9, scope: !51, inlinedAt: !60)
!62 = !DILocation(line: 11, column: 28, scope: !17)
!63 = !DILocation(line: 11, column: 2, scope: !17)
!64 = !DILocation(line: 12, column: 1, scope: !17)
!65 = !DISubprogram(name: "regmap_read", scope: !23, file: !23, line: 1327, type: !66, flags: DIFlagPrototyped, spFlags: DISPFlagOptimized)
!66 = !DISubroutineType(types: !67)
!67 = !{!54, !21, !5, !68}
!68 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !5, size: 64)
!69 = !DISubprogram(name: "regmap_write", scope: !23, file: !23, line: 1312, type: !70, flags: DIFlagPrototyped, spFlags: DISPFlagOptimized)
!70 = !DISubroutineType(types: !71)
!71 = !{!54, !21, !5, !5}
!72 = !DISubprogram(name: "regmap_bulk_read", scope: !23, file: !23, line: 1333, type: !73, flags: DIFlagPrototyped, spFlags: DISPFlagOptimized)
!73 = !DISubroutineType(types: !74)
!74 = !{!54, !21, !5, !75, !76}
!75 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: null, size: 64)
!76 = !DIDerivedType(tag: DW_TAG_typedef, name: "size_t", file: !77, line: 61, baseType: !78)
!77 = !DIFile(filename: "vendor/linux/include/linux/types.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "f19e794e841a113fbff9daca66bd7531")
!78 = !DIDerivedType(tag: DW_TAG_typedef, name: "__kernel_size_t", file: !79, line: 72, baseType: !80)
!79 = !DIFile(filename: "vendor/linux/include/uapi/asm-generic/posix_types.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "d9e6f1745c0d66a727722b7c6ecbf749")
!80 = !DIDerivedType(tag: DW_TAG_typedef, name: "__kernel_ulong_t", file: !79, line: 16, baseType: !81)
!81 = !DIBasicType(name: "unsigned long", size: 64, encoding: DW_ATE_unsigned)
!82 = !DISubprogram(name: "regmap_update_bits_base", scope: !23, file: !23, line: 1337, type: !83, flags: DIFlagPrototyped, spFlags: DISPFlagOptimized)
!83 = !DISubroutineType(types: !84)
!84 = !{!54, !21, !5, !5, !5, !85, !86, !86}
!85 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !86, size: 64)
!86 = !DIDerivedType(tag: DW_TAG_typedef, name: "bool", file: !77, line: 34, baseType: !87)
!87 = !DIBasicType(name: "_Bool", size: 8, encoding: DW_ATE_boolean)
