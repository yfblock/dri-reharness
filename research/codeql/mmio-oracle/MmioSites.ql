import cpp

from FunctionCall call
where call.getTarget().getName().regexpMatch(
        "(read|write)[lbwq]|ioread(8|16|32)|iowrite(8|16|32)")
select call.getFile().getBaseName(),
       call.getEnclosingFunction().getName(),
       call.getLocation().getStartLine(),
       call.getTarget().getName()
