ENTRY { author title year } {} {}
FUNCTION {begin.bib} { "\begin{thebibliography}{9}" write$ newline$ }
FUNCTION {end.bib} { "\end{thebibliography}" write$ newline$ }
FUNCTION {article} {
  "\bibitem{" write$ cite$ write$ "}" write$ newline$
  author write$ ". " write$ title write$ ". " write$ year write$ "." write$ newline$
}
READ
EXECUTE {begin.bib}
ITERATE {call.type$}
EXECUTE {end.bib}
