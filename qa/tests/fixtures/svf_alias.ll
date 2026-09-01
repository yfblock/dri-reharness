; ModuleID = '/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/svf_alias.c'
source_filename = "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/svf_alias.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

; Function Attrs: nounwind uwtable
define dso_local void @svf_alias_probe() local_unnamed_addr #0 !dbg !14 {
  %1 = tail call ptr @ioremap(i64 noundef 4096, i64 noundef 256) #3, !dbg !22
  tail call void @llvm.dbg.value(metadata ptr %1, metadata !19, metadata !DIExpression()), !dbg !23
  tail call void @llvm.dbg.value(metadata ptr %1, metadata !21, metadata !DIExpression()), !dbg !23
  %2 = getelementptr inbounds i8, ptr %1, i64 32, !dbg !24
  call void @llvm.dbg.value(metadata i32 1, metadata !25, metadata !DIExpression()), !dbg !34
  call void @llvm.dbg.value(metadata ptr %2, metadata !33, metadata !DIExpression()), !dbg !34
  tail call void asm sideeffect "movl $0,$1", "r,*m,~{memory},~{dirflag},~{fpsr},~{flags}"(i32 1, ptr nonnull elementtype(i32) %2) #3, !dbg !36, !srcloc !37
  ret void, !dbg !38
}

declare !dbg !39 ptr @ioremap(i64 noundef, i64 noundef) local_unnamed_addr #1

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare void @llvm.dbg.value(metadata, metadata, metadata) #2

attributes #0 = { nounwind uwtable "min-legal-vector-width"="0" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #1 = { "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #2 = { nocallback nofree nosync nounwind speculatable willreturn memory(none) }
attributes #3 = { nounwind }

!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!6, !7, !8, !9, !10, !11, !12}
!llvm.ident = !{!13}

!0 = distinct !DICompileUnit(language: DW_LANG_C11, file: !1, producer: "Ubuntu clang version 18.1.3 (1ubuntu1)", isOptimized: true, runtimeVersion: 0, emissionKind: FullDebug, retainedTypes: !2, splitDebugInlining: false, nameTableKind: None)
!1 = !DIFile(filename: "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/svf_alias.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "c4362a1b9000617a9e1834a5281ec142")
!2 = !{!3}
!3 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !4, size: 64)
!4 = !DIDerivedType(tag: DW_TAG_volatile_type, baseType: !5)
!5 = !DIBasicType(name: "unsigned int", size: 32, encoding: DW_ATE_unsigned)
!6 = !{i32 7, !"Dwarf Version", i32 5}
!7 = !{i32 2, !"Debug Info Version", i32 3}
!8 = !{i32 1, !"wchar_size", i32 4}
!9 = !{i32 8, !"PIC Level", i32 2}
!10 = !{i32 7, !"PIE Level", i32 2}
!11 = !{i32 7, !"uwtable", i32 2}
!12 = !{i32 7, !"debug-info-assignment-tracking", i1 true}
!13 = !{!"Ubuntu clang version 18.1.3 (1ubuntu1)"}
!14 = distinct !DISubprogram(name: "svf_alias_probe", scope: !15, file: !15, line: 3, type: !16, scopeLine: 4, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !18)
!15 = !DIFile(filename: "qa/tests/fixtures/svf_alias.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "c4362a1b9000617a9e1834a5281ec142")
!16 = !DISubroutineType(types: !17)
!17 = !{null}
!18 = !{!19, !21}
!19 = !DILocalVariable(name: "base", scope: !14, file: !15, line: 5, type: !20)
!20 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: null, size: 64)
!21 = !DILocalVariable(name: "alias", scope: !14, file: !15, line: 6, type: !20)
!22 = !DILocation(line: 5, column: 23, scope: !14)
!23 = !DILocation(line: 0, scope: !14)
!24 = !DILocation(line: 8, column: 18, scope: !14)
!25 = !DILocalVariable(name: "val", arg: 1, scope: !26, file: !27, line: 67, type: !5)
!26 = distinct !DISubprogram(name: "writel", scope: !27, file: !27, line: 67, type: !28, scopeLine: 67, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagLocalToUnit | DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !32)
!27 = !DIFile(filename: "vendor/linux/arch/x86/include/asm/io.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "7255a33f32535fc68bd0d1cd99111699")
!28 = !DISubroutineType(types: !29)
!29 = !{null, !5, !30}
!30 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !31, size: 64)
!31 = !DIDerivedType(tag: DW_TAG_volatile_type, baseType: null)
!32 = !{!25, !33}
!33 = !DILocalVariable(name: "addr", arg: 2, scope: !26, file: !27, line: 67, type: !30)
!34 = !DILocation(line: 0, scope: !26, inlinedAt: !35)
!35 = distinct !DILocation(line: 8, column: 2, scope: !14)
!36 = !DILocation(line: 67, column: 1, scope: !26, inlinedAt: !35)
!37 = !{i64 2149613617}
!38 = !DILocation(line: 9, column: 1, scope: !14)
!39 = !DISubprogram(name: "ioremap", scope: !27, file: !27, line: 195, type: !40, flags: DIFlagPrototyped, spFlags: DISPFlagOptimized)
!40 = !DISubroutineType(types: !41)
!41 = !{!20, !42, !50}
!42 = !DIDerivedType(tag: DW_TAG_typedef, name: "resource_size_t", file: !43, line: 178, baseType: !44)
!43 = !DIFile(filename: "vendor/linux/include/linux/types.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "f19e794e841a113fbff9daca66bd7531")
!44 = !DIDerivedType(tag: DW_TAG_typedef, name: "phys_addr_t", file: !43, line: 168, baseType: !45)
!45 = !DIDerivedType(tag: DW_TAG_typedef, name: "u64", file: !46, line: 23, baseType: !47)
!46 = !DIFile(filename: "vendor/linux/include/asm-generic/int-ll64.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "12ca7bdb629352cc4c9a492f86b435a7")
!47 = !DIDerivedType(tag: DW_TAG_typedef, name: "__u64", file: !48, line: 31, baseType: !49)
!48 = !DIFile(filename: "vendor/linux/include/uapi/asm-generic/int-ll64.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "f4d0ec5bcdd84e825a78a7add39d54dd")
!49 = !DIBasicType(name: "unsigned long long", size: 64, encoding: DW_ATE_unsigned)
!50 = !DIBasicType(name: "unsigned long", size: 64, encoding: DW_ATE_unsigned)
